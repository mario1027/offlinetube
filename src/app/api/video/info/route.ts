import { NextRequest, NextResponse } from 'next/server'

const BACKEND_URL = 'http://localhost:8001'

export async function GET(request: NextRequest) {
  const searchParams = request.nextUrl.searchParams
  const url = searchParams.get('url')

  if (!url) {
    return NextResponse.json({ error: 'URL parameter is required' }, { status: 400 })
  }

  try {
    const response = await fetch(`${BACKEND_URL}/api/video/info?url=${encodeURIComponent(url)}`)

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ detail: 'Unknown error' }))
      return NextResponse.json(
        { error: errorData.detail || 'Failed to get video info' },
        { status: response.status }
      )
    }

    const data = await response.json()
    return NextResponse.json(data)
  } catch (error) {
    console.error('Video info API error:', error)
    return NextResponse.json({ error: 'Failed to get video information' }, { status: 500 })
  }
}
