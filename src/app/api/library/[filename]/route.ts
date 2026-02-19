import { NextRequest, NextResponse } from 'next/server'

const BACKEND_URL = 'http://localhost:8001'

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ filename: string }> }
) {
  const { filename } = await params

  try {
    const response = await fetch(`${BACKEND_URL}/api/library/${encodeURIComponent(filename)}`, {
      method: 'DELETE'
    })
    const data = await response.json()
    return NextResponse.json(data)
  } catch (error) {
    console.error('Delete video API error:', error)
    return NextResponse.json({ error: 'Failed to delete video' }, { status: 500 })
  }
}
