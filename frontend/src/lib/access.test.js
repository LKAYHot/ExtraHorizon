import { afterEach, describe, expect, it, vi } from 'vitest'
import { getAccess, login, logout } from './api.js'

function reply(status, body) {
  return Promise.resolve({ ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) })
}

describe('remote access API', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('asks whether this browser needs the key', async () => {
    const fetch = vi.fn(() => reply(200, { required: true, ok: false, configured: true, transport: 'cloudflare' }))
    vi.stubGlobal('fetch', fetch)
    expect(await getAccess()).toMatchObject({ required: true, transport: 'cloudflare' })
    expect(fetch).toHaveBeenCalledWith('/api/access', { cache: 'no-store' })
  })

  it('sends the key once as JSON (never in the URL) and maps the refusals', async () => {
    const fetch = vi.fn()
      .mockReturnValueOnce(reply(401, { code: 'wrong_key', message: 'That key is not right.' }))
      .mockReturnValueOnce(reply(429, { code: 'too_many_attempts', retry_after_s: 540 }))
      .mockReturnValueOnce(reply(200, { required: true, ok: true }))
    vi.stubGlobal('fetch', fetch)
    await expect(login('guess')).rejects.toMatchObject({ code: 'wrong_key', status: 401 })
    await expect(login('guess')).rejects.toMatchObject({ code: 'too_many_attempts', retryAfter: 540 })
    expect(await login('the-key')).toMatchObject({ ok: true })
    const [url, init] = fetch.mock.calls[2]
    expect(url).toBe('/api/access')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ key: 'the-key' })
  })

  it('logs out with DELETE', async () => {
    const fetch = vi.fn(() => reply(200, { ok: false }))
    vi.stubGlobal('fetch', fetch)
    await logout()
    expect(fetch).toHaveBeenCalledWith('/api/access', { method: 'DELETE' })
  })
})
