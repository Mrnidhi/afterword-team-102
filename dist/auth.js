const route = location.pathname === '/signup' ? 'signup' : 'login';
const next = new URLSearchParams(location.search).get('next') || '/app/';
const signup = route === 'signup';
document.title = signup ? 'Create account — Afterword' : 'Sign in — Afterword';
document.querySelector('#form-eyebrow').textContent = signup ? 'CREATE YOUR SPACE' : 'WELCOME BACK';
document.querySelector('#form-title').textContent = signup ? 'Create a private workspace.' : 'Sign in to your workspace.';
document.querySelector('#form-description').textContent = signup ? 'Your account is stored only on this HP-hosted Afterword installation.' : 'Use your local Afterword account to continue.';
document.querySelector('#signup-fields').hidden = !signup;
document.querySelector('#password').autocomplete = signup ? 'new-password' : 'current-password';
document.querySelector('#submit-button').innerHTML = signup ? 'Create account <span>→</span>' : 'Sign in <span>→</span>';
document.querySelector('#auth-switch').innerHTML = signup ? 'Already have an account? <a href="/login">Sign in</a>' : 'New to Afterword? <a href="/signup">Create a private account</a>';
document.querySelector('#auth-form').addEventListener('submit', async event => {
  event.preventDefault(); const error = document.querySelector('#form-error'); const submit = document.querySelector('#submit-button'); error.textContent = '';
  const data = Object.fromEntries(new FormData(event.currentTarget));
  if (signup && !data.display_name.trim()) { error.textContent = 'Enter a display name.'; return; }
  submit.disabled = true; submit.textContent = signup ? 'Creating account…' : 'Signing in…';
  try {
    const response = await fetch(`/api/auth/${route}`, {method:'POST', headers:{'Content-Type':'application/json'}, credentials:'same-origin', body:JSON.stringify(data)});
    const body = await response.json(); if (!response.ok) throw new Error(body.detail || 'Please try again.');
    sessionStorage.setItem('afterword-csrf', body.csrf_token); location.assign(next.startsWith('/') ? next : '/app/');
  } catch (err) { error.textContent = err.message; submit.disabled = false; submit.innerHTML = signup ? 'Create account <span>→</span>' : 'Sign in <span>→</span>'; }
});
