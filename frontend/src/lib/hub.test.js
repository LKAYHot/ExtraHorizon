import { describe, expect, it } from 'vitest'
import { itemOf, minutes, refsOf, safeUrl } from './hub.svelte.js'
import { renderMarkdown } from './markdown.js'

const report = {
  id: 'hub_1', kind: 'unstuck',
  items: [{ ref: 'S1', type: 'package' }, { ref: 'S2', type: 'stackoverflow' }],
  peers: [{ ref: 'K1', title: 'cv2 in a venv' }],
  mentors: [{ ref: 'M1', name: 'Test Mentor Kai', source: 'board' }],
}

describe('hub results', () => {
  it('lists refs in panel order and finds any of them', () => {
    expect(refsOf(report)).toEqual(['S1', 'S2', 'K1', 'M1'])
    expect(itemOf(report, 'M1').name).toBe('Test Mentor Kai')
    expect(itemOf(report, 'S9')).toBeNull()
    expect(refsOf(null)).toEqual([])
  })

  it('formats how long a roadblock has blocked them', () => {
    expect(minutes(12)).toBe('12 min')
    expect(minutes(65)).toBe('1 h 05 min')
    expect(minutes(null)).toBe('')
  })

  it('shows only plain web links from public APIs and the board', () => {
    expect(safeUrl('https://stackoverflow.com/a/1')).toBe('https://stackoverflow.com/a/1')
    expect(safeUrl('javascript:alert(1)')).toBeNull()
    expect(safeUrl('data:text/html,<b>x</b>')).toBeNull()
    expect(safeUrl('https://example.org/"onmouseover=x')).toBeNull()
    expect(safeUrl(undefined)).toBeNull()
  })
})

describe('hub IDs in her answers', () => {
  it('become buttons only for results on screen ("Amazon S3" stays text)', () => {
    const html = renderMarkdown('Try S2 first; your Amazon S3 bucket is fine. F1 too.', { hids: new Set(['S1', 'S2']) })
    expect(html).toContain('data-hid="S2"')
    expect(html).not.toContain('data-hid="S3"')
    expect(html).not.toContain('data-fid') // finding IDs only in analysis answers
  })

  it('products named like an ID stay text even when that ID is on screen', () => {
    const hids = new Set(['S3', 'M2', 'L2', 'S1'])
    const html = renderMarkdown('Your Amazon S3 bucket, the M2 Mac and the L2 cache are fine; S1 is the fix.', { hids })
    expect(html).toContain('data-hid="S1"')
    expect(html).not.toContain('data-hid="S3"')
    expect(html).not.toContain('data-hid="M2"')
    expect(html).not.toContain('data-hid="L2"')
    expect(renderMarkdown('Mind s3 and S3.', { hids })).toContain('data-hid="S3"') // a bare S3 is her result
  })

  it('never inside links, and not at all without results on screen', () => {
    expect(renderMarkdown('[S2](https://example.org)', { hids: new Set(['S2']) })).not.toContain('data-hid')
    expect(renderMarkdown('S2', {})).not.toContain('data-hid')
  })
})
