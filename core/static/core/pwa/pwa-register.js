if ("serviceWorker" in navigator) {
    if (window.isSecureContext) {
        window.addEventListener('load', function() {
            var scriptElement = document.getElementById('pwa-register-script');
            if (scriptElement) {
                var swUrl = scriptElement.getAttribute('data-sw-url');
                var swScope = scriptElement.getAttribute('data-sw-scope');
                
                if (swUrl && swScope) {
                    navigator.serviceWorker.register(swUrl, {
                        scope: swScope,
                        updateViaCache: "none"
                    }).catch(function(error) {
                        console.error('Falha ao registrar Service Worker:', error);
                    });
                }
            }
        });
    }
}
