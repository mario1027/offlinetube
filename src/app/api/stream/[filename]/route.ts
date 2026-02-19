import { NextRequest, NextResponse } from 'next/server'

const BACKEND_URL = 'http://localhost:8001'

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ filename: string }> }
) {
  const { filename } = await params

  try {
    const response = await fetch(`${BACKEND_URL}/api/stream/${encodeURIComponent(filename)}`)

    if (!response.ok) {
      return NextResponse.json({ error: 'Video not found' }, { status: 404 })
    }

    const contentType = response.headers.get('content-type') || 'video/mp4'
    const contentLength = response.headers.get('content-length')

    const headers = new Headers()
    headers.set('Content-Type', contentType)
    if (contentLength) {
      headers.set('Content-Length', contentLength)
    }
    headers.set('Accept-Ranges', 'bytes')

    return new Response(response.body, {
      status: 200,
      headers
    })
  } catch (error) {
    console.error('Stream API error:', error)
    return NextResponse.json({ error: 'Failed to stream video' }, { status: 500 })
  }
}
