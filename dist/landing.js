let deferredInstall;
window.addEventListener('beforeinstallprompt', event => { event.preventDefault(); deferredInstall = event; });
document.querySelectorAll('[data-install]').forEach(button => button.addEventListener('click', async () => {
  const message = document.querySelector('#install-message');
  if (button.dataset.install === 'android' && deferredInstall) {
    deferredInstall.prompt(); await deferredInstall.userChoice; deferredInstall = null;
    message.textContent = 'Afterword can now be opened from your device like an app.';
  } else if (button.dataset.install === 'ios') {
    message.textContent = 'On iPhone or iPad, choose Share in Safari, then Add to Home Screen.';
  } else {
    message.textContent = 'Use your browser menu and choose Install app or Add to Home Screen.';
  }
}));
if ('serviceWorker' in navigator) window.addEventListener('load', () => navigator.serviceWorker.register('/sw.js'));
