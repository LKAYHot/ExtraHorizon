import { describe, expect, it } from 'vitest'
import { renderMarkdown } from './markdown.js'

// Tutor answers are rendered with {@html}; model output must never become live HTML.
describe('renderMarkdown', () => {
  it('escapes raw HTML from the model', () => {
    expect(renderMarkdown('<img src=x onerror=alert(1)>')).not.toContain('<img')
    expect(renderMarkdown('<script>alert(1)</script>')).toContain('&lt;script&gt;')
  })
  it('refuses javascript: and data: links', () => {
    expect(renderMarkdown('[x](javascript:alert(1))')).not.toContain('href')
    expect(renderMarkdown('![i](data:text/html;base64,PHNjcmlwdD4=)')).not.toContain('<img')
  })
  it('never renders remote images (no third-party requests from model output)', () => {
    expect(renderMarkdown('![tracker](https://evil.example/pixel.png)')).not.toContain('<img')
  })
  it('opens normal links safely in a new tab and keeps code blocks', () => {
    expect(renderMarkdown('[ok](https://example.com)')).toContain('rel="noopener noreferrer"')
    expect(renderMarkdown('```python\nprint(1)\n```')).toContain('<pre><code class="language-python">')
  })
})

describe('voice cues in answers', () => {
  it('renders delivery cues and sounds as stage directions, not as text or links', () => {
    const html = renderMarkdown('[huffy and flustered] Hmph. [sighing] Fine, I will explain.')
    expect(html).toContain('<span class="cue mood"')
    expect(html).toContain('>huffy and flustered</span>')
    expect(html).toContain('<span class="cue sound"')
    expect(html).not.toContain('[huffy')
  })
  it('hides timing cues and trims stray spaces inside a cue', () => {
    expect(renderMarkdown('One. [break] Two.')).toContain('cue timing')
    expect(renderMarkdown('[ curious] Eh?')).toContain('>curious</span>')
  })
  it('keeps real links working and escapes HTML inside a cue', () => {
    expect(renderMarkdown('[docs](https://example.com)')).toContain('href="https://example.com"')
    const html = renderMarkdown('[<b>loud</b>] hi')
    expect(html).not.toContain('<b>')
    expect(html).toContain('&lt;b&gt;')
  })
})
