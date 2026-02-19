"""
OfflineTube API - Backend FastAPI con yt-dlp
"""

import os
import json
import re
import subprocess
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

        # Intentar obtener información con múltiples opciones (probar web primero,
        # y reintentar con otros clientes si la lista de formatos es muy limitada)
        all_opts = [
            # Cliente web con configuración mínima (mejor para obtener todos los formatos)
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
        ]

        info = None
        last_error = None

        for opts in all_opts:
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)

                    # Si obtuvimos info pero la lista de formatos es muy limitada,
                    # intentamos con el siguiente cliente para obtener más calidades.
                    if isinstance(info, dict):
                        fmts = info.get('formats') or []
                        if len(fmts) < 2:
                            info = None
                            continue

                    if info:
                        break
            except Exception as e:
                last_error = e
                continue
        
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
        
        # Filtrar formatos de video
        video_formats = []
        seen_resolutions = set()
        
        for fmt in info.get('formats', []):
            height = fmt.get('height')
            if height and fmt.get('vcodec') != 'none':
                if height not in seen_resolutions:
                    seen_resolutions.add(height)
                    filesize = fmt.get('filesize') or fmt.get('filesize_approx', 0)
                    video_formats.append({
                        'format_id': fmt.get('format_id', ''),
                        'ext': fmt.get('ext', 'mp4'),
                        'resolution': f"{fmt.get('width', 0)}x{height}",
                        'height': height,
                        'fps': fmt.get('fps', 0) or 0,
                        'filesize': filesize,
                        'filesize_formatted': format_filesize(filesize),
                        'vcodec': fmt.get('vcodec', ''),
                        'acodec': fmt.get('acodec', 'none'),
                        'has_audio': fmt.get('acodec') != 'none' and fmt.get('acodec') is not None,
                    })
        
        # Si no hay formatos, agregar opciones por defecto
        if not video_formats:
            video_formats = [
                {'format_id': 'best', 'ext': 'mp4', 'resolution': 'Mejor calidad', 'height': 1080, 'fps': 30, 'filesize': 0, 'filesize_formatted': 'N/A', 'vcodec': 'h264', 'acodec': 'aac', 'has_audio': True},
                {'format_id': 'best[height<=720]', 'ext': 'mp4', 'resolution': '720p', 'height': 720, 'fps': 30, 'filesize': 0, 'filesize_formatted': 'N/A', 'vcodec': 'h264', 'acodec': 'aac', 'has_audio': True},
                {'format_id': 'best[height<=480]', 'ext': 'mp4', 'resolution': '480p', 'height': 480, 'fps': 30, 'filesize': 0, 'filesize_formatted': 'N/A', 'vcodec': 'h264', 'acodec': 'aac', 'has_audio': True},
            ]
        else:
            # Añadir calidades estándar si faltan (para que la UI siempre muestre opciones)
            existing_heights = {vf.get('height') for vf in video_formats if vf.get('height')}
            standard_heights = [1080, 720, 480, 360]
            for h in standard_heights:
                if h not in existing_heights:
                    video_formats.append({
                        'format_id': f'best[height<={h}]',
                        'ext': 'mp4',
                        'resolution': f'{h}p',
                        'height': h,
                        'fps': 30,
                        'filesize': 0,
                        'filesize_formatted': 'N/A',
                        'vcodec': 'h264',
                        'acodec': 'aac',
                        'has_audio': True,
                    })

            # Ordenar por resolución descendente y eliminar duplicados por format_id
            video_formats.sort(key=lambda x: -x['height'])
            seen_ids = set()
            deduped = []
            for vf in video_formats:
                fid = vf.get('format_id')
                if fid in seen_ids:
                    continue
                seen_ids.add(fid)
                deduped.append(vf)
            video_formats = deduped[:8]
        
        return {
            'id': video_id,
            'title': info.get('title', 'Sin título'),
            'description': (info.get('description', '') or '')[:500],
            'thumbnail': f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg",
            'duration': info.get('duration', 0) or 0,
            'duration_formatted': format_duration(info.get('duration', 0)),
            'uploader': info.get('uploader', 'Desconocido'),
            'view_count': info.get('view_count', 0) or 0,
            'formats': video_formats,
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

@app.get("/api/video/download")
async def download_video(
    url: str = Query(..., min_length=1),
    format_id: str = Query(None),
    resolution: str = Query("720")
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
            
            safe_title = re.sub(r'[^\w\s-]', '', title)[:50]
            safe_title = re.sub(r'[-\s]+', '_', safe_title)
            
            if format_id and format_id != 'best' and not format_id.startswith('best['):
                format_spec = format_id + "+bestaudio/best"
            else:
                format_spec = f"best[height<={resolution}]+bestaudio/best[height<={resolution}]/best"
            
            output_path = DOWNLOAD_DIR / f"{safe_title}_{video_id}.%(ext)s"
            
            ydl_opts_download = {
                'quiet': False,
                'no_warnings': False,
                'format': format_spec,
                'outtmpl': str(output_path),
                'merge_output_format': 'mp4',
                'extractor_args': {
                    'youtube': {
                        'player_client': ['android', 'ios', 'web'],
                    }
                },
            }
            
            with yt_dlp.YoutubeDL(ydl_opts_download) as ydl_download:
                ydl_download.download([url])
            
            for file in DOWNLOAD_DIR.glob(f"{safe_title}_{video_id}.*"):
                if file.is_file():
                    return {
                        'success': True,
                        'filename': file.name,
                        'filepath': str(file),
                        'size': file.stat().st_size
                    }
            
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
                
                videos.append({
                    'id': video_id,
                    'title': file.stem.replace('_', ' '),
                    'filename': file.name,
                    'filepath': str(file),
                    'thumbnail': f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg" if len(video_id) == 11 else '',
                    'duration': 0,
                    'resolution': 'N/A',
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
                            requested_height = int(resolution)
                        except Exception:
                            requested_height = 0

                        # if requested resolution isn't available, notify client and use the highest available
                        resolution_to_use = requested_height
                        if requested_height and max_height and requested_height > max_height:
                            await websocket.send_json({
                                'status': 'info',
                                'message': f'Requested {requested_height}p not available; will download {max_height}p',
                                'selected_height': max_height
                            })
                            resolution_to_use = max_height

                        # initial status — progress unknown until yt-dlp reports totals
                        await websocket.send_json({
                            'status': 'downloading',
                            'progress': None,
                            'speed': 'N/A',
                            'eta': 'N/A',
                            'filename': f"{safe_title}_{video_id}.mp4",
                            'requested_height': requested_height if requested_height else None
                        })

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
                                total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                                downloaded = d.get('downloaded_bytes', 0)

                                # avoid division by zero; if total is 0 use None to indicate unknown
                                progress = (downloaded / total * 100) if total else None

                                payload = {
                                    'status': 'downloading',
                                    # keep `progress` as None when unknown so the UI shows an indeterminate state
                                    'progress': progress,
                                    'speed': format_filesize(d.get('speed', 0)) + '/s',
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

                        # use resolution_to_use determined earlier
                        fmt_spec = f'best[height<={resolution_to_use}]' + '+bestaudio/best' if resolution_to_use else 'best'

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

                        with yt_dlp.YoutubeDL(ydl_opts_download) as ydl_download:
                            ydl_download.download([url])

                        for file in DOWNLOAD_DIR.glob(f"{safe_title}_{video_id}.*"):
                            if file.is_file():
                                await websocket.send_json({
                                    'status': 'complete',
                                    'progress': 100,
                                    'filename': file.name,
                                    'filepath': str(file),
                                    'size': file.stat().st_size,
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
