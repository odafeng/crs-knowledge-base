// Sign-in links for browser tests, made with the local Supabase admin API instead of a real email (D1 #67).
// Env: SUPABASE_URL, SUPABASE_SERVICE_KEY (the local demo key; never a real project's key).
const { SUPABASE_URL, SUPABASE_SERVICE_KEY } = process.env;

async function admin(path, body) {
  if (!SUPABASE_URL || !SUPABASE_SERVICE_KEY) throw new Error('SUPABASE_URL and SUPABASE_SERVICE_KEY are required');
  const response = await fetch(`${SUPABASE_URL}/auth/v1${path}`, {
    method: 'POST',
    headers: { apikey: SUPABASE_SERVICE_KEY, Authorization: `Bearer ${SUPABASE_SERVICE_KEY}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`${path} ${response.status} ${await response.text()}`);
  return response.json();
}

/** A one-time sign-in link for `email` on `origin`, as the email template builds it. */
async function signInLink(origin, email) {
  const link = await admin('/admin/generate_link', { type: 'magiclink', email });
  return `${origin}/auth/callback/?token_hash=${link.hashed_token ?? link.properties.hashed_token}&type=email`;
}

module.exports = { signInLink };
