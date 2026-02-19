"""
OfflineTube API - Backend FastAPI con yt-dlp
"""

import os
import json
import re
import subprocess
import urllib.request
import tempfile
import shutil
import threading
import time
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import yt_dlp

# Configuración
DOWNLOAD_DIR = Path(os.environ.get("OFFLINETUBE_DOWNLOAD_DIR", Path.home() / "Downloads" / "offlinetube"))
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="OfflineTube API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def format_filesize(bytes_size: int) -> str:
    if bytes_size is None or bytes_size == 0:
        return "N/A"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_size < 1024:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024
    return f"{bytes_size:.1f} TB"

def format_duration(seconds: int) -> str:
    if seconds is None or seconds == 0:
        return "0:00"
    hours, remainder = divmod(int(seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def embed_metadata_into_mp4(filepath: Path, info: Dict[str, Any]):
    """Embed basic metadata + thumbnail into an mp4/mkv file using ffmpeg (best-effort).
    Silently falla si ffmpeg no está disponible o hay errores.
    """
    try:
        if not filepath.exists():
            return
        suffix = filepath.suffix.lower()
        if suffix not in ['.mp4', '.m4a', '.mkv', '.mp3']:
            return

        title = (info.get('title') or '')
        uploader = (info.get('uploader') or '')
        webpage = info.get('webpage_url') or info.get('id') or ''

        thumb_url = info.get('thumbnail')
        thumb_path = None
        if thumb_url:
            try:
                td = tempfile.NamedTemporaryFile(delete=False, suffix='.jpg')
                td.close()
                urllib.request.urlretrieve(thumb_url, td.name)
                thumb_path = td.name
            except Exception as e:
                print(f"embed: failed to download thumbnail: {e}")
                thumb_path = None

        tmp_out = filepath.with_suffix(filepath.suffix + '.tmp')

        cmd = ['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-i', str(filepath)]
        meta_args = []
        if title:
            meta_args += ['-metadata', f'title={title}']
        if uploader:
            meta_args += ['-metadata', f'artist={uploader}']
        if webpage:
            meta_args += ['-metadata', f'comment={webpage}']

        if thumb_path:
            # attach cover art (map streams so we keep original streams and add attached_pic)
            cmd += ['-i', thumb_path, '-map', '0', '-map', '1']
            cmd += ['-c', 'copy']
            cmd += meta_args
            cmd += ['-disposition:v:1', 'attached_pic', str(tmp_out)]
        else:
            cmd += ['-c', 'copy']
            cmd += meta_args
            cmd += [str(tmp_out)]

        subprocess.run(cmd, check=True)
        shutil.move(str(tmp_out), str(filepath))
        if thumb_path:
            try:
                os.unlink(thumb_path)
            except Exception:
                pass
    except Exception as e:
        print(f"embed_metadata_into_mp4 failed for {filepath}: {e}")

# Opciones de yt-dlp optimizadas para evitar bloqueos
def get_ydl_opts(extract_flat=False):
    """Retorna opciones de yt-dlp optimizadas para evitar bloqueos de YouTube"""
    opts = {
        'quiet': True,
        'no_warnings': True,
        # Usar clientes móviles que tienen menos restricciones
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'ios', 'web'],
                'player_skip': ['webpage', 'configs'],
            }
        },
        # Headers para parecer un cliente móvil real
        'http_headers': {
            'User-Agent': 'com.google.android.youtube/19.12.35 (Linux; U; Android 14) gzip',
            'X-YouTube-Client-Name': '3',
            'X-YouTube-Client-Version': '19.12.35',
        },
    }
    
    if extract_flat:
        opts['extract_flat'] = True
        
    return opts

@app.get("/")
async def root():
    return {"message": "OfflineTube API funcionando", "version": "1.0.0"}

@app.get("/api/search")
async def search_videos(q: str = Query(..., min_length=1), max_results: int = Query(20, ge=1, le=50)):
    """Busca videos en YouTube"""
    try:
        search_url = f"ytsearch{max_results}:{q}"
        
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'playlistend': max_results,
        }
        
        results = []
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(search_url, download=False)
            
            if info and 'entries' in info:
                for entry in info['entries']:
                    if entry:
                        video_id = entry.get('id', '')
                        results.append({
                            'id': video_id,
                            'title': entry.get('title', 'Sin título'),
                            'thumbnail': f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
                            'duration': entry.get('duration', 0) or 0,
                            'uploader': entry.get('uploader') or entry.get('channel') or 'Desconocido',
                            'view_count': entry.get('view_count', 0) or 0,
                            'url': f"https://www.youtube.com/watch?v={video_id}"
                        })
        
        return {"results": results, "query": q}
    
    except Exception as e:
        print(f"Search error: {e}")
        return {"results": [], "query": q, "error": str(e)}

@app.get("/api/trending")
async def get_trending():
    """Obtiene videos populares"""
    try:
        search_url = "ytsearch20:música popular"
        
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'playlistend': 20,
        }
        
        results = []
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(search_url, download=False)
            
            if info and 'entries' in info:
                for entry in info['entries']:
                    if entry:
                        video_id = entry.get('id', '')
                        results.append({
                            'id': video_id,
                            'title': entry.get('title', 'Sin título'),
                            'thumbnail': f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
                            'duration': entry.get('duration', 0) or 0,
                            'uploader': entry.get('uploader') or entry.get('channel') or 'Desconocido',
                            'view_count': entry.get('view_count', 0) or 0,
                            'url': f"https://www.youtube.com/watch?v={video_id}"
                        })
        
        return {"results": results}
    
    except Exception as e:
        print(f"Trending error: {e}")
        return {"results": [], "error": str(e)}

@app.get("/api/video/info")
async def get_video_info(url: str = Query(..., min_length=1)):
    """Obtiene información del video y formatos usando yt-dlp"""
    try:
        video_id = None
        
        # Extraer ID del video de la URL
        patterns = [
            r'(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})',
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                video_id = match.group(1)
                break
        
        if not video_id:
            return {"error": "No se pudo extraer el ID del video"}

        # Intentar obtener información con múltiples opciones (probar extracción "por defecto" y varios clientes)
        # - Primero intentamos una extracción *por defecto* (sin forzar player_client) porque suele devolver la lista más completa
        # - Luego probamos clientes específicos (web / android / ios) como fallback
        all_opts = [
            # Cliente web (intento rápido y fiable para exponer adaptative formats)
            {
                'quiet': True,
                'no_warnings': True,
                'extractor_args': {
                    'youtube': {
                        'player_client': ['web'],
                        'player_skip': ['webpage'],
                    }
                },
            },
            # Cliente Android
            {
                'quiet': True,
                'no_warnings': True,
                'extractor_args': {
                    'youtube': {
                        'player_client': ['android'],
                    }
                },
            },
            # Cliente iOS
            {
                'quiet': True,
                'no_warnings': True,
                'extractor_args': {
                    'youtube': {
                        'player_client': ['ios'],
                    }
                },
            },
            # extracción por defecto (fallback, puede ser más lenta) — se prueba al final
            {'quiet': True, 'no_warnings': True},
        ]

        info = None
        sanitized_info = None
        last_error = None

        # Try all clients and pick the best candidate (highest available height / most formats)
        best_candidate = None
        best_max_height = -1

        for opts in all_opts:
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    candidate = ydl.extract_info(url, download=False)

                    # sanitize candidate info if possible
                    try:
                        candidate_sanitized = ydl.sanitize_info(candidate)
                    except Exception:
                        candidate_sanitized = candidate

                    if not isinstance(candidate, dict):
                        continue

                    fmts = candidate.get('formats') or []
                    if not fmts:
                        continue

                    # compute the highest height available for this candidate
                    max_h = max((f.get('height') or 0) for f in fmts)

                    # choose candidate with larger max height, break ties by number of formats
                    if (max_h > best_max_height) or (max_h == best_max_height and len(fmts) > len((best_candidate[0].get('formats') if best_candidate else []))):
                        best_candidate = (candidate, candidate_sanitized)
                        best_max_height = max_h

            except Exception as e:
                last_error = e
                continue

        if best_candidate:
            info, sanitized_info = best_candidate
        else:
            info = None
            sanitized_info = None
        
        if not info:
            # Retornar información básica si no podemos obtener formatos
            return {
                'id': video_id,
                'title': f'Video {video_id}',
                'description': 'No se pudo obtener la descripción',
                'thumbnail': f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg",
                'duration': 0,
                'duration_formatted': 'N/A',
                'uploader': 'Desconocido',
                'view_count': 0,
                'formats': [
                    {'format_id': 'best', 'ext': 'mp4', 'resolution': '1080p', 'height': 1080, 'fps': 30, 'filesize': 0, 'filesize_formatted': 'N/A', 'vcodec': 'h264', 'acodec': 'aac', 'has_audio': True},
                    {'format_id': 'best[height<=720]', 'ext': 'mp4', 'resolution': '720p', 'height': 720, 'fps': 30, 'filesize': 0, 'filesize_formatted': 'N/A', 'vcodec': 'h264', 'acodec': 'aac', 'has_audio': True},
                    {'format_id': 'best[height<=480]', 'ext': 'mp4', 'resolution': '480p', 'height': 480, 'fps': 30, 'filesize': 0, 'filesize_formatted': 'N/A', 'vcodec': 'h264', 'acodec': 'aac', 'has_audio': True},
                    {'format_id': 'best[height<=360]', 'ext': 'mp4', 'resolution': '360p', 'height': 360, 'fps': 30, 'filesize': 0, 'filesize_formatted': 'N/A', 'vcodec': 'h264', 'acodec': 'aac', 'has_audio': True},
                ],
                'url': url,
                'limited_info': True,
                'can_play_online': True,
            }
        
        # Construir lista completa de formatos (video, audio y combinados) exponiendo `format_id` real
        # Preferir la lista 'sanitizada' si está disponible — usarla como fuente única para generar el listado que devolveremos
        full_formats_list = (sanitized_info.get('formats') if sanitized_info else (info.get('formats') if isinstance(info, dict) else []))
        formats = []
        seen_ids = set()
        for fmt in (full_formats_list or []):
            fid = fmt.get('format_id') or ''
            if not fid or fid in seen_ids:
                continue
            seen_ids.add(fid)
            has_video = fmt.get('vcodec') and fmt.get('vcodec') != 'none'
            has_audio = fmt.get('acodec') and fmt.get('acodec') != 'none'
            filesize = fmt.get('filesize') or fmt.get('filesize_approx') or 0
            formats.append({
                'format_id': fid,
                'format': fmt.get('format'),
                'format_note': fmt.get('format_note') or '',
                'ext': fmt.get('ext') or '',
                'protocol': fmt.get('protocol') or '',
                'height': fmt.get('height'),
                'width': fmt.get('width'),
                'fps': fmt.get('fps') or 0,
                'filesize': filesize,
                'filesize_formatted': format_filesize(filesize),
                'vcodec': fmt.get('vcodec'),
                'acodec': fmt.get('acodec'),
                'has_audio': has_audio,
                'has_video': has_video,
                'resolution': f"{fmt.get('height')}p" if fmt.get('height') else (fmt.get('format_note') or fmt.get('ext') or 'audio'),
            })

        # Ordenar: combinados (video+audio) primero por altura, luego video-only, luego audio-only
        formats.sort(key=lambda f: (
            0 if (f['has_video'] and f['has_audio']) else (1 if f['has_video'] else 2),
            -(f.get('height') or 0),
            -(f.get('filesize') or 0)
        ))

        # Para compatibilidad con la UI antigua, también verificamos que haya formatos con video disponibles
        # (no limitamos la cantidad — devolvemos todos los formatos encontrados)
        video_formats = [f for f in formats if f['has_video']]
        if not video_formats:
            # fallback sintético (como antes)
            video_formats = [
                {'format_id': 'best', 'ext': 'mp4', 'resolution': 'Mejor calidad', 'height': 1080, 'fps': 30, 'filesize': 0, 'filesize_formatted': 'N/A', 'vcodec': 'h264', 'acodec': 'aac', 'has_audio': True, 'has_video': True},
                {'format_id': 'best[height<=720]', 'ext': 'mp4', 'resolution': '720p', 'height': 720, 'fps': 30, 'filesize': 0, 'filesize_formatted': 'N/A', 'vcodec': 'h264', 'acodec': 'aac', 'has_audio': True, 'has_video': True},
                {'format_id': 'best[height<=480]', 'ext': 'mp4', 'resolution': '480p', 'height': 480, 'fps': 30, 'filesize': 0, 'filesize_formatted': 'N/A', 'vcodec': 'h264', 'acodec': 'aac', 'has_audio': True, 'has_video': True},
            ]
        
        return {
            'id': video_id,
            'title': info.get('title', 'Sin título'),
            'description': (info.get('description', '') or '')[:2000],
            'thumbnail': f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg",
            'duration': info.get('duration', 0) or 0,
            'duration_formatted': format_duration(info.get('duration', 0)),
            'uploader': info.get('uploader', 'Desconocido'),
            'view_count': info.get('view_count', 0) or 0,
            'formats': formats,
            # full, sanitized formats (raw) to allow the UI to display everything
            'raw_formats': (sanitized_info.get('formats') if sanitized_info else info.get('formats') if isinstance(info, dict) else []),
            'url': url,
            'can_play_online': True,
        }
    
    except yt_dlp.utils.DownloadError as e:
        error_msg = str(e)
        video_id = None
        
        # Intentar extraer ID del video
        patterns = [
            r'(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})',
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                video_id = match.group(1)
                break
        
        if video_id:
            # Retornar info básica para poder descargar
            return {
                'id': video_id,
                'title': f'Video {video_id}',
                'description': 'Información limitada - el video se puede descargar',
                'thumbnail': f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg",
                'duration': 0,
                'duration_formatted': 'N/A',
                'uploader': 'Desconocido',
                'view_count': 0,
                'formats': [
                    {'format_id': 'best', 'ext': 'mp4', 'resolution': 'Mejor calidad', 'height': 1080, 'fps': 30, 'filesize': 0, 'filesize_formatted': 'N/A', 'vcodec': 'h264', 'acodec': 'aac', 'has_audio': True},
                    {'format_id': 'best[height<=720]', 'ext': 'mp4', 'resolution': '720p', 'height': 720, 'fps': 30, 'filesize': 0, 'filesize_formatted': 'N/A', 'vcodec': 'h264', 'acodec': 'aac', 'has_audio': True},
                    {'format_id': 'best[height<=480]', 'ext': 'mp4', 'resolution': '480p', 'height': 480, 'fps': 30, 'filesize': 0, 'filesize_formatted': 'N/A', 'vcodec': 'h264', 'acodec': 'aac', 'has_audio': True},
                ],
                'url': url,
                'limited_info': True,
                'can_play_online': True,
            }
        
        return {"error": error_msg}
    except Exception as e:
        print(f"Video info error: {e}")
        return {"error": str(e)}

@app.get("/api/playlist/info")
async def get_playlist_info(url: str = Query(..., min_length=1)):
    """Obtiene la lista de entradas de una playlist (rápido - extract_flat)"""
    try:
        # si la URL contiene `list=` y además `watch?v=`, forzar la URL tipo /playlist?list=ID
        list_match = None
        m = re.search(r'[?&]list=([a-zA-Z0-9_-]+)', url)
        if m:
            list_match = m.group(1)

        playlist_url = url
        if list_match:
            playlist_url = f"https://www.youtube.com/playlist?list={list_match}"

        # intentar múltiples configuraciones de extractor (web/android/ios) para mejorar chances
        all_opts = [
            get_ydl_opts(extract_flat=True),
            {**get_ydl_opts(extract_flat=True), 'extractor_args': {'youtube': {'player_client': ['web']}}},
            {**get_ydl_opts(extract_flat=True), 'extractor_args': {'youtube': {'player_client': ['android']}}},
            {**get_ydl_opts(extract_flat=True), 'extractor_args': {'youtube': {'player_client': ['ios']}}},
        ]

        info = None
        for opts in all_opts:
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    candidate = ydl.extract_info(playlist_url, download=False)
                    if candidate and isinstance(candidate, dict) and candidate.get('entries'):
                        info = candidate
                        break
            except Exception:
                continue

        if not info:
            # último intento con opciones por defecto
            with yt_dlp.YoutubeDL(get_ydl_opts(extract_flat=True)) as ydl:
                info = ydl.extract_info(playlist_url, download=False)

            # Normalizar entradas de playlist
            entries = []
            for e in info.get('entries') or []:
                if not e:
                    continue
                vid = e.get('id') or e.get('url') or None
                if not vid:
                    continue
                entries.append({
                    'id': vid,
                    'title': e.get('title') or f'Video {vid}',
                    'thumbnail': e.get('thumbnail') or f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
                    'duration': e.get('duration') or 0,
                    'duration_formatted': format_duration(e.get('duration') or 0),
                    'uploader': e.get('uploader') or e.get('uploader_id') or '',
                    'url': f"https://www.youtube.com/watch?v={vid}"
                })

            return {
                'id': info.get('id'),
                'title': info.get('title') or 'Playlist',
                'uploader': info.get('uploader') or '',
                'count': len(entries),
                'entries': entries
            }
    except Exception as e:
        print(f"Playlist info error: {e}")
        return {"error": str(e)}

@app.get("/api/video/download")
async def download_video(
    url: str = Query(..., min_length=1),
    format_id: str = Query(None),
    resolution: str = Query("720"),
    use_ffmpeg: bool = Query(False)
):
    """Descarga un video"""
    try:
        # Opciones para obtener info básica
        base_opts = {
            'quiet': True,
            'no_warnings': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'ios', 'web'],
                }
            },
        }
        
        with yt_dlp.YoutubeDL(base_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            video_id = info.get('id', '')
            title = info.get('title', 'video')
            
            # keep full title in metadata sidecar but use a filesystem-friendly filename (longer allowed)
            safe_title = re.sub(r'[^\w\s-]', '', title)[:120]
            safe_title = re.sub(r'[-\s]+', '_', safe_title)

            # Save metadata sidecar so offline library shows full metadata
            try:
                meta = {
                    'id': video_id,
                    'title': info.get('title'),
                    'description': info.get('description') or '',
                    'thumbnail': f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg",
                    'duration': info.get('duration', 0) or 0,
                    'duration_formatted': format_duration(info.get('duration', 0)),
                    'uploader': info.get('uploader') or info.get('channel') or 'Desconocido',
                    'view_count': info.get('view_count', 0) or 0,
                    'tags': info.get('tags') or [],
                    'formats': [
                        {
                            'format_id': f.get('format_id'),
                            'ext': f.get('ext'),
                            'resolution': f"{f.get('width', 0)}x{f.get('height')}" if f.get('height') else 'N/A',
                            'height': f.get('height'),
                            'filesize': f.get('filesize') or f.get('filesize_approx', 0),
                            'filesize_formatted': format_filesize(f.get('filesize') or f.get('filesize_approx', 0) or 0),
                            'vcodec': f.get('vcodec'),
                            'acodec': f.get('acodec'),
                        }
                        for f in (info.get('formats') or [])
                    ]
                }
                with open(DOWNLOAD_DIR / f"{safe_title}_{video_id}.json", 'w', encoding='utf-8') as mf:
                    json.dump(meta, mf, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"Failed to write metadata sidecar: {e}")
            
            # Determine format_spec: if a format_id was provided, prefer it; if it's a video-only format, append bestaudio
            if format_id:
                if '+' in format_id or format_id.startswith('best') or '[' in format_id:
                    format_spec = format_id
                else:
                    # inspect available formats to decide whether to add audio
                    sel = next((f for f in (info.get('formats') or []) if f.get('format_id') == format_id), None)
                    if sel and (sel.get('acodec') in (None, 'none')):
                        format_spec = f"{format_id}+bestaudio/best"
                    else:
                        format_spec = format_id
            else:
                format_spec = f"best[height<={resolution}]+bestaudio/best[height<={resolution}]/best"

            output_path = DOWNLOAD_DIR / f"{safe_title}_{video_id}.%(ext)s"

            ydl_opts_download = {
                'quiet': False,
                'no_warnings': False,
                'format': format_spec,
                'outtmpl': str(output_path),
                'merge_output_format': 'mp4',
                'progress_hooks': [],
                'extractor_args': {
                    'youtube': {
                        'player_client': ['android', 'ios', 'web'],
                    }
                },
            }

            if use_ffmpeg:
                ydl_opts_download['writeinfojson'] = True
                ydl_opts_download['writethumbnail'] = True
                ydl_opts_download['writesubtitles'] = True
                ydl_opts_download['writeautomaticsub'] = True

            with yt_dlp.YoutubeDL(ydl_opts_download) as ydl_download:
                ydl_download.download([url])

            # try to embed metadata/thumbnail into output file (best-effort) when requested
            for file in DOWNLOAD_DIR.glob(f"{safe_title}_{video_id}.*"):
                if file.is_file():
                    # attempt to embed metadata/thumbnail via ffmpeg if requested
                    if use_ffmpeg:
                        try:
                            embed_metadata_into_mp4(file, info)
                        except Exception:
                            pass

                    return {'success': True, 'filename': file.name, 'size': file.stat().st_size}

            # if we reach here, the expected output file wasn't found
            return {'success': False, 'error': 'Archivo no encontrado'}
    
    except Exception as e:
        return {'success': False, 'error': str(e)}

@app.get("/api/library")
async def get_library():
    """Lista videos descargados"""
    try:
        videos = []
        
        if not DOWNLOAD_DIR.exists():
            return {"videos": []}
        
        for file in DOWNLOAD_DIR.iterdir():
            if file.is_file() and file.suffix in ['.mp4', '.webm', '.mkv', '.mp3', '.m4a']:
                video_id_match = re.search(r'_([a-zA-Z0-9_-]{11})\.', file.name)
                video_id = video_id_match.group(1) if video_id_match else file.stem

                # try to load metadata sidecar JSON if exists
                meta = {}
                try:
                    sidecar = DOWNLOAD_DIR / (file.stem + '.json')
                    if sidecar.exists():
                        with open(sidecar, 'r', encoding='utf-8') as sf:
                            meta = json.load(sf)
                except Exception as e:
                    print(f"Failed to read metadata sidecar for {file.name}: {e}")
                
                videos.append({
                    'id': meta.get('id', video_id),
                    'title': meta.get('title') or file.stem.replace('_', ' '),
                    'description': meta.get('description', ''),
                    'filename': file.name,
                    'filepath': str(file),
                    'thumbnail': meta.get('thumbnail') or (f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg" if len(video_id) == 11 else ''),
                    'duration': meta.get('duration', 0),
                    'duration_formatted': meta.get('duration_formatted', format_duration(meta.get('duration', 0))),
                    'uploader': meta.get('uploader', 'Desconocido'),
                    'view_count': meta.get('view_count', 0),
                    'formats': meta.get('formats', []),
                    'resolution': meta.get('formats', [{}])[0].get('height') or 'N/A',
                    'size': file.stat().st_size,
                    'size_formatted': format_filesize(file.stat().st_size),
                    'downloaded_at': datetime.fromtimestamp(file.stat().st_mtime).isoformat()
                })
        
        videos.sort(key=lambda x: x['downloaded_at'], reverse=True)
        return {"videos": videos}
    
    except Exception as e:
        return {"videos": [], "error": str(e)}

@app.get("/api/stream/{filename}")
async def stream_video(filename: str):
    """Transmite un video"""
    filepath = DOWNLOAD_DIR / filename
    
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    
    return FileResponse(path=filepath, media_type="video/mp4", filename=filename)

@app.delete("/api/library/{filename}")
async def delete_video(filename: str):
    """Elimina un video"""
    try:
        filepath = DOWNLOAD_DIR / filename
        
        if filepath.exists():
            filepath.unlink()
            return {"success": True, "message": f"{filename} eliminado"}
        
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# WebSocket para descargas con progreso
@app.websocket("/ws/download")
async def websocket_download(websocket: WebSocket):
    await websocket.accept()
    print("WS: client connected to /ws/download")

    try:
        while True:
            data = await websocket.receive_text()
            print(f"WS: received message -> {data}")
            message = json.loads(data)

            if message.get('type') == 'download':
                url = message.get('url')
                resolution = message.get('resolution', '720')

                try:
                    # Obtener info básica primero
                    ydl_opts = {
                        'quiet': True,
                        'no_warnings': True,
                        'extractor_args': {
                            'youtube': {
                                'player_client': ['android', 'ios', 'web'],
                            }
                        },
                    }

                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(url, download=False)
                        video_id = info.get('id', '')
                        title = info.get('title', 'video')

                        safe_title = re.sub(r'[^\w\s-]', '', title)[:50]
                        safe_title = re.sub(r'[-\s]+', '_', safe_title)

                        # determine available heights from extracted info
                        available_heights = sorted({fmt.get('height') for fmt in (info.get('formats') or []) if fmt.get('height')})
                        max_height = max(available_heights) if available_heights else 0

                        try:
                            requested_height = int(resolution) if str(resolution).isdigit() else 0
                        except Exception:
                            requested_height = 0
                        # accept explicit format_id from client (so UI selection is respected)
                        requested_format = message.get('format_id')

                        # determine resolution_to_use default
                        resolution_to_use = requested_height

                        if requested_format:
                            # try to find selected format in extracted info
                            sel = next((f for f in (info.get('formats') or []) if f.get('format_id') == requested_format), None)
                            if sel:
                                # if the selected format is video-only, note it; we will add bestaudio when building fmt_spec
                                if sel.get('height'):
                                    resolution_to_use = sel.get('height')

                        if requested_height and max_height and requested_height > max_height:
                            await websocket.send_json({
                                'status': 'info',
                                'message': f'Requested {requested_height}p not available; will download {max_height}p',
                                'selected_height': max_height
                            })
                            resolution_to_use = max_height

                        # try to estimate total bytes from the extracted `info` (filesize / filesize_approx)
                        estimated_total = None

                        def _filesize_of(fmt):
                            return fmt.get('filesize') or fmt.get('filesize_approx') or None

                        # helper to find bestaudio/video candidates
                        formats_list = info.get('formats') or []

                        if requested_format:
                            # cases: explicit id(s), compound specs, or 'best[...]' patterns
                            if '+' in requested_format:
                                # requested like '137+140' -> sum known sizes for each id when available
                                parts = [p for p in requested_format.split('+') if p]
                                total_sum = 0
                                found_any = False
                                for pid in parts:
                                    sel = next((f for f in formats_list if f.get('format_id') == pid), None)
                                    if sel:
                                        fs = _filesize_of(sel)
                                        if fs:
                                            total_sum += fs
                                            found_any = True
                                if found_any:
                                    estimated_total = total_sum
                            elif requested_format.startswith('best') or '[' in requested_format:
                                # pattern-based: estimate by selecting best video <= resolution + bestaudio
                                # video candidate
                                v_cand = None
                                for f in sorted(formats_list, key=lambda x: (x.get('height') or 0), reverse=True):
                                    if f.get('vcodec') and f.get('vcodec') != 'none' and (not f.get('acodec') or f.get('acodec') == 'none'):
                                        if resolution_to_use and f.get('height') and f.get('height') <= resolution_to_use:
                                            v_cand = f
                                            break
                                # audio candidate (best available)
                                a_cand = next((f for f in sorted(formats_list, key=lambda x: x.get('abr') or 0, reverse=True) if not f.get('vcodec') or f.get('vcodec') == 'none'), None)
                                sizes = []
                                if v_cand:
                                    fs = _filesize_of(v_cand)
                                    if fs:
                                        sizes.append(fs)
                                if a_cand:
                                    fs = _filesize_of(a_cand)
                                    if fs:
                                        sizes.append(fs)
                                if sizes:
                                    estimated_total = sum(sizes)
                            else:
                                # single format id
                                sel = next((f for f in formats_list if f.get('format_id') == requested_format), None)
                                if sel:
                                    fs = _filesize_of(sel)
                                    if fs:
                                        # if sel is video-only, try to add audio estimate
                                        if sel.get('acodec') in (None, 'none'):
                                            a = next((f for f in formats_list if (not f.get('vcodec') or f.get('vcodec') == 'none')), None)
                                            a_fs = _filesize_of(a) if a else None
                                            estimated_total = fs + (a_fs or 0) if fs else (a_fs or None)
                                        else:
                                            estimated_total = fs
                        else:
                            # no explicit format -> try to find a combined format or best video+audio pair
                            combined = next((f for f in sorted(formats_list, key=lambda x: (x.get('height') or 0), reverse=True) if f.get('vcodec') and f.get('acodec') and ((not resolution_to_use) or (f.get('height') or 0) <= resolution_to_use)), None)
                            if combined:
                                fs = _filesize_of(combined)
                                if fs:
                                    estimated_total = fs
                            else:
                                # fallback: best video (<= resolution) + best audio
                                v_cand = next((f for f in sorted(formats_list, key=lambda x: (x.get('height') or 0), reverse=True) if f.get('vcodec') and (not resolution_to_use or (f.get('height') or 0) <= resolution_to_use)), None)
                                a_cand = next((f for f in sorted(formats_list, key=lambda x: x.get('abr') or 0, reverse=True) if not f.get('vcodec') or f.get('vcodec') == 'none'), None)
                                sizes = []
                                if v_cand:
                                    fs = _filesize_of(v_cand)
                                    if fs:
                                        sizes.append(fs)
                                if a_cand:
                                    fs = _filesize_of(a_cand)
                                    if fs:
                                        sizes.append(fs)
                                if sizes:
                                    estimated_total = sum(sizes)

                        # initial status — include any filesize estimate we computed so UI can show % immediately
                        initial_payload = {
                            'status': 'downloading',
                            'progress': None,
                            'speed': 'N/A',
                            'eta': 'N/A',
                            'filename': f"{safe_title}_{video_id}.mp4",
                            'requested_height': requested_height if requested_height else None,
                            'requested_format_id': requested_format if requested_format else None,
                            'downloaded_bytes': 0
                        }

                        if estimated_total:
                            initial_payload['total_bytes'] = int(estimated_total)

                        await websocket.send_json(initial_payload)

                        # --- Start a background poller that watches the output file size as a fallback ---
                        stop_poller = threading.Event()
                        base_name = f"{safe_title}_{video_id}"

                        def _poll_output_file(poll_interval=0.5):
                            last_size = 0
                            last_time = time.time()
                            while not stop_poller.is_set():
                                try:
                                    matches = list(DOWNLOAD_DIR.glob(f"{base_name}.*"))
                                    size = 0
                                    if matches:
                                        size = max((m.stat().st_size for m in matches if m.is_file()), default=0)

                                    now = time.time()
                                    if size != last_size:
                                        # estimate speed from file growth
                                        delta = now - last_time if last_time else 1.0
                                        speed = int((size - last_size) / delta) if delta > 0 else None

                                        # compute ETA when we have an estimated_total
                                        eta_str = 'N/A'
                                        if estimated_total and speed and speed > 0:
                                            rem = max(0, int(estimated_total) - size)
                                            eta_seconds = int(rem / speed)
                                            eta_str = f"{eta_seconds}s"

                                        payload = {
                                            'status': 'downloading',
                                            'downloaded_bytes': size,
                                            'total_bytes': int(estimated_total) if estimated_total else None,
                                            'speed_bps': speed,
                                            'speed': (format_filesize(speed) + '/s') if speed else 'N/A',
                                            'eta': eta_str,
                                            'filename': f"{base_name}.mp4"
                                        }

                                        try:
                                            loop = __import__('asyncio').get_event_loop()
                                            loop.call_soon_threadsafe(
                                                lambda: __import__('asyncio').create_task(websocket.send_json(payload))
                                            )
                                        except Exception:
                                            pass

                                        last_size = size
                                        last_time = now
                                except Exception:
                                    pass

                                time.sleep(poll_interval)

                        poller_thread = threading.Thread(target=_poll_output_file, daemon=True)
                        poller_thread.start()

                        def progress_hook(d):
                            import asyncio
                            # Debug log for progress hook
                            try:
                                print(f"WS: progress_hook event -> {d.get('status')} - downloaded={d.get('downloaded_bytes')} total={d.get('total_bytes') or d.get('total_bytes_estimate')}")
                            except Exception:
                                pass

                            # try to extract the actual selected format from info_dict
                            info_dict = d.get('info_dict') or {}
                            selected_format_id = None
                            selected_height = None
                            try:
                                if info_dict.get('requested_formats'):
                                    rf = info_dict.get('requested_formats')[0]
                                    selected_format_id = rf.get('format_id')
                                    selected_height = rf.get('height')
                                else:
                                    selected_format_id = info_dict.get('format_id') or info_dict.get('requested_format')
                                    selected_height = info_dict.get('height')
                            except Exception:
                                pass

                            if d['status'] == 'downloading':
                                total = d.get('total_bytes') or d.get('total_bytes_estimate') or None
                                downloaded = d.get('downloaded_bytes', 0)

                                # avoid division by zero; if total is 0 use None to indicate unknown
                                progress = (downloaded / total * 100) if total else None

                                speed_bps = d.get('speed') or None

                                payload = {
                                    'status': 'downloading',
                                    # numeric percentage (0-100) when total known; otherwise None
                                    'progress': round(progress, 2) if isinstance(progress, float) else progress,
                                    # raw byte counts for the UI to compute an exact percentage if desired
                                    'downloaded_bytes': downloaded,
                                    'total_bytes': total,
                                    # numeric speed in bytes/sec (may be None) + human string for backwards compatibility
                                    'speed_bps': speed_bps,
                                    'speed': (format_filesize(speed_bps) + '/s') if speed_bps else 'N/A',
                                    'eta': str(d.get('eta', 'N/A')) + 's',
                                    'filename': f"{safe_title}_{video_id}.mp4",
                                    'selected_format_id': selected_format_id,
                                    'selected_height': selected_height
                                }

                                try:
                                    loop = asyncio.get_event_loop()
                                    loop.call_soon_threadsafe(
                                        lambda: asyncio.create_task(websocket.send_json(payload))
                                    )
                                except Exception as e:
                                    print(f"WS: failed to send progress payload: {e}")

                            elif d['status'] == 'finished':
                                # stop the file poller (if running) — progress_hook runs in yt-dlp thread
                                try:
                                    stop_poller.set()
                                except Exception:
                                    pass
                                try:
                                    loop = asyncio.get_event_loop()
                                    loop.call_soon_threadsafe(
                                        lambda: asyncio.create_task(websocket.send_json({
                                            'status': 'finished',
                                            'progress': 100,
                                            'filename': f"{safe_title}_{video_id}.mp4",
                                            'selected_format_id': selected_format_id,
                                            'selected_height': selected_height
                                        }))
                                    )
                                except Exception as e:
                                    print(f"WS: failed to send finished payload: {e}")

                        output_path = DOWNLOAD_DIR / f"{safe_title}_{video_id}.%(ext)s"

                        # build format spec using requested_format (if provided) or resolution_to_use
                        requested_format = message.get('format_id')
                        use_ffmpeg = bool(message.get('use_ffmpeg', False))

                        if requested_format:
                            if '+' in requested_format or requested_format.startswith('best') or '[' in requested_format:
                                fmt_spec = requested_format
                            else:
                                sel = next((f for f in (info.get('formats') or []) if f.get('format_id') == requested_format), None)
                                if sel and (sel.get('acodec') in (None, 'none')):
                                    fmt_spec = f"{requested_format}+bestaudio/best"
                                else:
                                    fmt_spec = requested_format
                        else:
                            fmt_spec = (f'best[height<={resolution_to_use}]'+ '+bestaudio/best') if resolution_to_use else 'best'

                        ydl_opts_download = {
                            'quiet': False,
                            'no_warnings': False,
                            'format': fmt_spec,
                            'outtmpl': str(output_path),
                            'merge_output_format': 'mp4',
                            'progress_hooks': [progress_hook],
                            'extractor_args': {
                                'youtube': {
                                    'player_client': ['android', 'ios', 'web'],
                                }
                            },
                        }

                        # enable extra postprocessing/embed options when user requests ffmpeg assistance
                        if use_ffmpeg:
                            ydl_opts_download['writeinfojson'] = True
                            ydl_opts_download['writethumbnail'] = True
                            # request subtitles when possible (yt-dlp will ignore unsupported flags)
                            ydl_opts_download['writesubtitles'] = True
                            ydl_opts_download['writeautomaticsub'] = True

                        try:
                            # log the chosen format spec for debugging
                            try:
                                print(f"WS: download fmt_spec -> {fmt_spec}")
                            except Exception:
                                pass

                            with yt_dlp.YoutubeDL(ydl_opts_download) as ydl_download:
                                ydl_download.download([url])
                        except Exception as download_exc:
                            # If yt-dlp complains about requested format not being available,
                            # retry using a resolution-based spec (best[height<=requested]+bestaudio/best)
                            err_str = str(download_exc)
                            print(f"WS: download failed -> {err_str}")
                            if 'Requested format is not available' in err_str or 'requested format is not available' in err_str.lower():
                                try:
                                    # build a resolution-based fallback fmt_spec
                                    if resolution_to_use:
                                        fallback_spec = f"best[height<={resolution_to_use}]+bestaudio/best"
                                    else:
                                        fallback_spec = 'best'

                                    print(f"WS: retrying with fallback fmt_spec -> {fallback_spec}")
                                    ydl_opts_download['format'] = fallback_spec
                                    with yt_dlp.YoutubeDL(ydl_opts_download) as ydl_download:
                                        ydl_download.download([url])
                                except Exception as retry_exc:
                                    print(f"WS: retry failed -> {retry_exc}")
                                    raise
                            else:
                                raise
                        finally:
                            try:
                                stop_poller.set()
                            except Exception:
                                pass

                        # write metadata sidecar for offline library
                        try:
                            meta = {
                                'id': video_id,
                                'title': info.get('title'),
                                'description': info.get('description') or '',
                                'thumbnail': f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg",
                                'duration': info.get('duration', 0) or 0,
                                'duration_formatted': format_duration(info.get('duration', 0)),
                                'uploader': info.get('uploader') or info.get('channel') or 'Desconocido',
                                'view_count': info.get('view_count', 0) or 0,
                                'formats': [
                                    {
                                        'format_id': f.get('format_id'),
                                        'ext': f.get('ext'),
                                        'resolution': f"{f.get('width', 0)}x{f.get('height')}" if f.get('height') else 'N/A',
                                        'height': f.get('height'),
                                        'filesize': f.get('filesize') or f.get('filesize_approx', 0),
                                        'filesize_formatted': format_filesize(f.get('filesize') or f.get('filesize_approx', 0) or 0),
                                        'vcodec': f.get('vcodec'),
                                        'acodec': f.get('acodec'),
                                    }
                                    for f in (info.get('formats') or [])
                                ]
                            }
                            with open(DOWNLOAD_DIR / f"{safe_title}_{video_id}.json", 'w', encoding='utf-8') as mf:
                                json.dump(meta, mf, ensure_ascii=False, indent=2)
                        except Exception as e:
                            print(f"Failed to write metadata sidecar (ws): {e}")

                        for file in DOWNLOAD_DIR.glob(f"{safe_title}_{video_id}.*"):
                            if file.is_file():
                                # attempt to embed metadata/thumbnail via ffmpeg if requested
                                if use_ffmpeg:
                                    try:
                                        embed_metadata_into_mp4(file, info)
                                    except Exception as e:
                                        print(f"embed failed (ws): {e}")

                                await websocket.send_json({
                                    'status': 'complete',
                                    'progress': 100,
                                    'filename': file.name,
                                    'filepath': str(file),
                                    'size': file.stat().st_size,
                                    'downloaded_bytes': file.stat().st_size,
                                    'total_bytes': file.stat().st_size,
                                    'speed_bps': None,
                                    'selected_height': selected_height if 'selected_height' in locals() else None,
                                    'selected_format_id': selected_format_id if 'selected_format_id' in locals() else None
                                })
                                break

                except Exception as e:
                    await websocket.send_json({
                        'status': 'error',
                        'error': str(e)
                    })

    except WebSocketDisconnect:
        print("WS: client disconnected")
        pass
    except Exception as e:
        print(f"WebSocket error: {e}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
