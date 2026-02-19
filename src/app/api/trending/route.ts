import { NextResponse } from 'next/server'

const BACKEND_URL = 'http://localhost:8001'

export async function GET() {
  try {
    const response = await fetch(`${BACKEND_URL}/api/trending`)
    const data = await response.json()
    return NextResponse.json(data)
  } catch (error) {
    console.error('Trending API error:', error)
    return NextResponse.json({ error: 'Failed to get trending videos' }, { status: 500 })
  }
}
