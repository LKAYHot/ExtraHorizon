import MarkdownIt from 'markdown-it'
import { cuePlugin } from './cues.js'

// html: false → any HTML the model emits is escaped, never injected.
const md = new MarkdownIt({ html: false, linkify: true, breaks: false, typographer: false })
// no remote images: a model answer must not make the browser contact third-party hosts
md.disable('image')
// the tutor's voice cues ([huffy and flustered], [sighing]) become small stage directions
md.use(cuePlugin)
// in analysis answers, finding IDs ("F146") become buttons that show the finding on the map; in hub answers,
// the IDs of the results on screen ("S2", "P1") become buttons that show that result
md.use(fidPlugin)

const defaultLink = md.renderer.rules.link_open ?? ((tokens, idx, options, env, self) => self.renderToken(tokens, idx, options))
md.renderer.rules.link_open = (tokens, idx, options, env, self) => {
  tokens[idx].attrSet('target', '_blank')
  tokens[idx].attrSet('rel', 'noopener noreferrer')
  return defaultLink(tokens, idx, options, env, self)
}

/** ``fids``: turn finding IDs into map buttons (analysis answers only — "F1 score" elsewhere stays text).
 *  ``hids``: the refs of the hub results on screen (a Set) — only those become buttons ("S3 bucket" stays text). */
export function renderMarkdown(text, { fids = false, hids = null } = {}) {
  return md.render(text ?? '', { fids, hids })
}

// ("Amazon S3", "an M2 Mac", "L2 cache" are products, not results)
const FID = /(?<!(?:[Aa]mazon|AWS|aws|[Aa]pple|MacBook) )\b(?:F\d{1,6}|[SLPMK]\d{1,2})\b(?!\s+(?:[Bb]uckets?|[Cc]hips?|[Cc]ache|Mac|MacBook|Pro|Max|Ultra|Air)\b)/g

function fidPlugin(md) {
  md.core.ruler.push('eh_fid', (state) => {
    const fids = !!state.env?.fids
    const hids = state.env?.hids
    if (!fids && !hids?.size) return
    const wanted = (id) => (id[0] === 'F' ? fids : !!hids?.has(id))
    for (const block of state.tokens) {
      if (block.type !== 'inline' || !block.children) continue
      const out = []
      let inLink = 0
      for (const t of block.children) {
        if (t.type === 'link_open') inLink++
        if (t.type === 'link_close') inLink--
        FID.lastIndex = 0
        if (t.type !== 'text' || inLink || !FID.test(t.content)) {
          out.push(t)
          continue
        }
        let last = 0
        FID.lastIndex = 0
        for (let m; (m = FID.exec(t.content)); ) {
          if (!wanted(m[0])) continue
          if (m.index > last) {
            const x = new state.Token('text', '', 0)
            x.content = t.content.slice(last, m.index)
            out.push(x)
          }
          const b = new state.Token(m[0][0] === 'F' ? 'eh_fid' : 'eh_hid', '', 0)
          b.content = m[0]
          out.push(b)
          last = m.index + m[0].length
        }
        if (last < t.content.length) {
          const x = new state.Token('text', '', 0)
          x.content = t.content.slice(last)
          out.push(x)
        }
      }
      block.children = out
    }
  })
  md.renderer.rules.eh_fid = (tokens, idx) => {
    const id = md.utils.escapeHtml(tokens[idx].content)
    return `<button type="button" class="fid" data-fid="${id}" title="Show ${id} on the map">${id}</button>`
  }
  md.renderer.rules.eh_hid = (tokens, idx) => {
    const id = md.utils.escapeHtml(tokens[idx].content)
    return `<button type="button" class="fid hid" data-hid="${id}" title="Show ${id} in the hub">${id}</button>`
  }
}
