import { NextResponse } from 'next/server'

const BACKEND_URL = 'http://localhost:8001'

export async function GET() {
  try {
    const response = await fetch(`${BACKEND_URL}/api/library`)
    const data = await response.json()
    return NextResponse.json(data)
  } catch (error) {
    console.error('Library API error:', error)
    return NextResponse.json({ error: 'Failed to get library' }, { status: 500 })
  }
}
