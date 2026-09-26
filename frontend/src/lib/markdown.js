import MarkdownIt from 'markdown-it'

// html: false → any HTML the model emits is escaped, never injected.
const md = new MarkdownIt({ html: false, linkify: true, breaks: false, typographer: false })
// no remote images: a model answer must not make the browser contact third-party hosts
md.disable('image')

const defaultLink = md.renderer.rules.link_open ?? ((tokens, idx, options, env, self) => self.renderToken(tokens, idx, options))
md.renderer.rules.link_open = (tokens, idx, options, env, self) => {
  tokens[idx].attrSet('target', '_blank')
  tokens[idx].attrSet('rel', 'noopener noreferrer')
  return defaultLink(tokens, idx, options, env, self)
}

export function renderMarkdown(text) {
  return md.render(text ?? '')
}
