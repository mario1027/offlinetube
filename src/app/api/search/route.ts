import { NextRequest, NextResponse } from 'next/server'

const BACKEND_URL = 'http://localhost:8001'

export async function GET(request: NextRequest) {
  const searchParams = request.nextUrl.searchParams
  const q = searchParams.get('q')
  const maxResults = searchParams.get('max_results') || '20'

  if (!q) {
    return NextResponse.json({ error: 'Query parameter "q" is required' }, { status: 400 })
  }

  try {
    const response = await fetch(
      `${BACKEND_URL}/api/search?q=${encodeURIComponent(q)}&max_results=${maxResults}`
    )
    const data = await response.json()
    return NextResponse.json(data)
  } catch (error) {
    console.error('Search API error:', error)
    return NextResponse.json({ error: 'Failed to search videos' }, { status: 500 })
  }
}
