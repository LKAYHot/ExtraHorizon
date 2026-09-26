import adapter from '@sveltejs/adapter-static'

/** @type {import('@sveltejs/kit').Config} */
export default {
  kit: {
    // Static single-page build (frontend/build) — served by the FastAPI backend in demo mode.
    adapter: adapter({ pages: 'build', assets: 'build', strict: true }),
  },
}
