// Local-first single-user app: everything (mic, recordings, localStorage
// session recovery) is browser-side, so SSR only adds failure modes.
export const ssr = false;
export const prerender = false;
