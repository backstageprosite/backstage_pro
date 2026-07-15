// Variável para guardar o evento beforeinstallprompt
let deferredInstallPrompt = null;

window.addEventListener("beforeinstallprompt", (event) => {
    // Impede o prompt nativo de aparecer sozinho
    event.preventDefault();
    // Salva o evento para acionar depois
    deferredInstallPrompt = event;
    
    // Mostra o botão de instalação
    const installBtn = document.getElementById("pwa-install-btn");
    if (installBtn) {
        installBtn.style.display = "block";
        installBtn.addEventListener("click", handleInstallClick);
    }
});

async function handleInstallClick() {
    if (!deferredInstallPrompt) {
        return;
    }
    
    // Dispara o prompt
    deferredInstallPrompt.prompt();
    
    // Aguarda a resposta do usuário
    const choiceResult = await deferredInstallPrompt.userChoice;
    
    // Independentemente da escolha, escondemos o botão e limpamos o evento
    deferredInstallPrompt = null;
    const installBtn = document.getElementById("pwa-install-btn");
    if (installBtn) {
        installBtn.style.display = "none";
    }
}

// Escuta quando a instalação de fato ocorre
window.addEventListener("appinstalled", (event) => {
    deferredInstallPrompt = null;
    const installBtn = document.getElementById("pwa-install-btn");
    if (installBtn) {
        installBtn.style.display = "none";
    }
});

function isIos() {
    return [
        'iPad Simulator',
        'iPhone Simulator',
        'iPod Simulator',
        'iPad',
        'iPhone',
        'iPod'
    ].includes(navigator.platform)
    // iPadOS 13+ se passa por macOS
    || (navigator.userAgent.includes("Mac") && "ontouchend" in document)
    || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
}

function isStandalone() {
    return window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;
}

window.addEventListener('load', () => {
    // Se já estiver instalado ou aberto no modo standalone, garantir que o botão não apareça
    if (isStandalone()) {
        const installBtn = document.getElementById("pwa-install-btn");
        if (installBtn) {
            installBtn.style.display = "none";
        }
        return;
    }

    // Tratamento para iOS (onde beforeinstallprompt não existe)
    if (isIos()) {
        const installBtn = document.getElementById("pwa-install-btn");
        if (installBtn) {
            installBtn.style.display = "block";
            installBtn.addEventListener("click", () => {
                // Abre o modal educativo usando Bootstrap (se existir na página)
                if (typeof bootstrap !== 'undefined') {
                    const modalElement = document.getElementById('iosInstallModal');
                    if (modalElement) {
                        const modal = new bootstrap.Modal(modalElement);
                        modal.show();
                    }
                }
            });
        }
    }
});
