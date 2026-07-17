document.addEventListener("DOMContentLoaded", function() {
    const card = document.getElementById("web-push-settings-card");
    if (!card) return;

    const btnMain = document.getElementById("web-push-btn-main");
    const btnMainText = document.getElementById("web-push-btn-main-text");
    const spinnerMain = document.getElementById("web-push-spinner-main");
    
    const btnSecondary = document.getElementById("web-push-btn-secondary");
    const spinnerSecondary = document.getElementById("web-push-spinner-secondary");
    
    const feedback = document.getElementById("web-push-feedback");
    const csrfToken = card.querySelector('[name=csrfmiddlewaretoken]')?.value;

    const urls = {
        publicKey: card.dataset.publicKeyUrl,
        status: card.dataset.statusUrl,
        subscribe: card.dataset.subscribeUrl,
        unsubscribe: card.dataset.unsubscribeUrl
    };
    const bandSlug = card.dataset.bandSlug;
    const expectedScope = card.dataset.expectedScope;

    const STATE = {
        UNSUPPORTED: 'UNSUPPORTED',
        IOS_NOT_INSTALLED: 'IOS_NOT_INSTALLED',
        PERMISSION_DEFAULT: 'PERMISSION_DEFAULT',
        PERMISSION_DENIED: 'PERMISSION_DENIED',
        PERMISSION_GRANTED_UNSUBSCRIBED: 'PERMISSION_GRANTED_UNSUBSCRIBED',
        SUBSCRIBED: 'SUBSCRIBED',
        PROCESSING: 'PROCESSING',
        ERROR: 'ERROR'
    };

    let currentState = null;

    function setState(state, message = "") {
        currentState = state;
        
        btnMain.disabled = false;
        btnMain.classList.remove("d-none");
        spinnerMain.classList.add("d-none");
        btnMain.removeAttribute("aria-busy");
        
        btnSecondary.disabled = false;
        btnSecondary.classList.add("d-none");
        spinnerSecondary.classList.add("d-none");
        btnSecondary.removeAttribute("aria-busy");
        
        feedback.classList.remove("text-danger");
        feedback.classList.add("text-primary");

        if (message) {
            feedback.textContent = message;
        }

        if (state === STATE.UNSUPPORTED) {
            btnMain.disabled = true;
            btnMainText.textContent = "Indisponível";
            feedback.textContent = "Este navegador não oferece suporte a notificações Push.";
        } else if (state === STATE.IOS_NOT_INSTALLED) {
            btnMain.disabled = true;
            btnMainText.textContent = "Indisponível";
            feedback.textContent = "No iPhone ou iPad, adicione este aplicativo à Tela de Início para ativar notificações.";
        } else if (state === STATE.PERMISSION_DEFAULT) {
            btnMainText.textContent = "Ativar notificações neste dispositivo";
            if (!message) feedback.textContent = "Permissão necessária.";
        } else if (state === STATE.PERMISSION_DENIED) {
            btnMain.disabled = true;
            btnMainText.textContent = "Bloqueado";
            feedback.classList.add("text-danger");
            feedback.textContent = "As notificações estão bloqueadas nas configurações do navegador.";
        } else if (state === STATE.PERMISSION_GRANTED_UNSUBSCRIBED) {
            btnMainText.textContent = "Conectar este dispositivo";
            if (!message) feedback.textContent = "Pronto para vincular.";
        } else if (state === STATE.SUBSCRIBED) {
            btnMain.classList.add("d-none");
            btnSecondary.classList.remove("d-none");
            if (!message) feedback.textContent = "Notificações ativadas neste dispositivo.";
        } else if (state === STATE.PROCESSING) {
            btnMain.disabled = true;
            btnMain.setAttribute("aria-busy", "true");
            spinnerMain.classList.remove("d-none");
            btnMainText.textContent = "Aguarde...";
            
            btnSecondary.disabled = true;
            btnSecondary.setAttribute("aria-busy", "true");
            if (!btnSecondary.classList.contains("d-none")) {
                spinnerSecondary.classList.remove("d-none");
            }
            if (!message) feedback.textContent = "Aguarde...";
        } else if (state === STATE.ERROR) {
            btnMainText.textContent = "Tentar novamente";
            feedback.classList.add("text-danger");
            if (!message) {
                feedback.textContent = "Ocorreu um erro ao configurar notificações.";
            }
        }
    }

    const isIOS =
        /iPad|iPhone|iPod/.test(navigator.userAgent) ||
        (
            navigator.platform === "MacIntel" &&
            navigator.maxTouchPoints > 1
        );

    const isStandalone =
        window.matchMedia("(display-mode: standalone)").matches ||
        window.navigator.standalone === true;

    function checkSupport() {
        if (!window.isSecureContext) return false;
        if (!("serviceWorker" in navigator)) return false;
        if (!("PushManager" in window)) return false;
        if (!("Notification" in window)) return false;
        return true;
    }

    function checkExactScope(registration) {
        const expectedScopeUrl = new URL(expectedScope, window.location.origin);
        const actualScopeUrl = new URL(registration.scope);
        return actualScopeUrl.href === expectedScopeUrl.href;
    }

    function urlBase64ToUint8Array(base64String) {
        if (typeof base64String !== 'string' || base64String.length === 0) {
            throw new Error("Invalid base64 string");
        }
        const padding = '='.repeat((4 - base64String.length % 4) % 4);
        const base64 = (base64String + padding).replace(/\-/g, '+').replace(/_/g, '/');

        const rawData = window.atob(base64);
        const outputArray = new Uint8Array(rawData.length);

        for (let i = 0; i < rawData.length; ++i) {
            outputArray[i] = rawData.charCodeAt(i);
        }
        if (outputArray.length !== 65 || outputArray[0] !== 0x04) {
            throw new Error("Invalid VAPID public key");
        }
        return outputArray;
    }
    
    function areArraysEqual(a, b) {
        if (!a || !b) return false;
        
        let arrA = a;
        if (a instanceof ArrayBuffer) {
            arrA = new Uint8Array(a);
        } else if (a.buffer && a.buffer instanceof ArrayBuffer) {
            arrA = new Uint8Array(a.buffer, a.byteOffset, a.byteLength);
        }

        let arrB = b;
        if (b instanceof ArrayBuffer) {
            arrB = new Uint8Array(b);
        } else if (b.buffer && b.buffer instanceof ArrayBuffer) {
            arrB = new Uint8Array(b.buffer, b.byteOffset, b.byteLength);
        }

        if (arrA.length !== arrB.length) return false;
        for (let i = 0; i < arrA.length; i++) {
            if (arrA[i] !== arrB[i]) return false;
        }
        return true;
    }

    async function init() {
        if (!checkSupport()) {
            return setState(STATE.UNSUPPORTED);
        }

        if (isIOS && !isStandalone) {
            return setState(STATE.IOS_NOT_INSTALLED);
        }

        if (Notification.permission === 'denied') {
            return setState(STATE.PERMISSION_DENIED);
        }

        try {
            const registration = await navigator.serviceWorker.ready;
            if (!checkExactScope(registration)) {
                return setState(STATE.ERROR, "Service Worker incompatível com esta página.");
            }

            const subscription = await registration.pushManager.getSubscription();

            if (!subscription) {
                if (Notification.permission === 'granted') {
                    return setState(STATE.PERMISSION_GRANTED_UNSUBSCRIBED);
                } else {
                    return setState(STATE.PERMISSION_DEFAULT);
                }
            } else {
                const response = await fetch(urls.status, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Accept': 'application/json',
                        'X-CSRFToken': csrfToken
                    },
                    credentials: 'same-origin',
                    cache: 'no-store',
                    body: JSON.stringify({ endpoint: subscription.endpoint })
                });

                if (response.ok) {
                    const data = await response.json();
                    if (data.subscribed) {
                        return setState(STATE.SUBSCRIBED);
                    } else {
                        return setState(STATE.PERMISSION_GRANTED_UNSUBSCRIBED);
                    }
                } else {
                    return setState(STATE.ERROR, "Não foi possível verificar o status atual.");
                }
            }
        } catch (error) {
            setState(STATE.ERROR, "Falha ao iniciar notificações.");
        }
    }

    async function handleSubscribe(isRetry = false) {
        setState(STATE.PROCESSING);
        
        if (!checkSupport()) {
            return setState(STATE.UNSUPPORTED);
        }

        try {
            if (Notification.permission === 'default') {
                const permissionResult = await Notification.requestPermission();
                if (permissionResult === 'denied') {
                    return setState(STATE.PERMISSION_DENIED);
                }
            } else if (Notification.permission === 'denied') {
                return setState(STATE.PERMISSION_DENIED);
            }

            const vapidResponse = await fetch(urls.publicKey, {
                method: 'GET',
                headers: { 'Accept': 'application/json' },
                credentials: 'same-origin',
                cache: 'no-store'
            });

            if (!vapidResponse.ok) {
                return setState(STATE.ERROR, "Falha ao obter configuração de notificações.");
            }

            const vapidData = await vapidResponse.json();
            const publicKeyArray = urlBase64ToUint8Array(vapidData.publicKey);

            const registration = await navigator.serviceWorker.ready;
            if (!checkExactScope(registration)) {
                return setState(STATE.ERROR, "Service Worker incompatível com esta página.");
            }
            
            async function deactivateOwnSubscriptionOnBackend(sub) {
                if (!sub || !sub.endpoint) throw new Error("No endpoint");
                const resp = await fetch(urls.unsubscribe, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Accept': 'application/json',
                        'X-CSRFToken': csrfToken
                    },
                    credentials: 'same-origin',
                    cache: 'no-store',
                    body: JSON.stringify({ endpoint: sub.endpoint })
                });
                if (resp.status !== 200) {
                    throw new Error("Failed backend unsubscribe");
                }
                return true;
            }

            let subscription = await registration.pushManager.getSubscription();

            if (subscription) {
                const currentKey = subscription.options.applicationServerKey;
                if (!areArraysEqual(currentKey, publicKeyArray)) {
                    try {
                        await deactivateOwnSubscriptionOnBackend(subscription);
                        const unsubOk = await subscription.unsubscribe();
                        if (!unsubOk) throw new Error("Local unsubscribe returned false");
                        subscription = null;
                    } catch (e) {
                        return setState(STATE.ERROR, "Falha ao desvincular chave antiga. Tente novamente mais tarde.");
                    }
                }
            }

            if (!subscription) {
                subscription = await registration.pushManager.subscribe({
                    userVisibleOnly: true,
                    applicationServerKey: publicKeyArray
                });
            }

            const subJSON = subscription.toJSON();
            if (!subJSON.endpoint || !subJSON.keys || !subJSON.keys.p256dh || !subJSON.keys.auth) {
                throw new Error("Invalid subscription JSON");
            }

            const subscribeResponse = await fetch(urls.subscribe, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                credentials: 'same-origin',
                cache: 'no-store',
                body: JSON.stringify({
                    endpoint: subJSON.endpoint,
                    keys: subJSON.keys
                })
            });

            if (subscribeResponse.ok || subscribeResponse.status === 201) {
                setState(STATE.SUBSCRIBED);
            } else if (subscribeResponse.status === 409) {
                if (isRetry) {
                    setState(STATE.ERROR, "Não foi possível vincular este dispositivo. Desative as notificações do aplicativo no navegador e tente novamente.");
                } else {
                    const unsubOk = await subscription.unsubscribe();
                    if (!unsubOk) {
                        return setState(STATE.ERROR, "Não foi possível remover a inscrição local em conflito.");
                    }
                    return handleSubscribe(true);
                }
            } else {
                setState(STATE.ERROR, "Falha ao registrar no servidor.");
            }
        } catch (error) {
            let msg = "Ocorreu um erro ao configurar notificações.";
            if (error.name === 'NotAllowedError') {
                return setState(STATE.PERMISSION_DENIED);
            } else if (error.name === 'AbortError') {
                msg = "A criação da assinatura foi abortada.";
            } else if (error.name === 'InvalidStateError') {
                msg = "Estado inválido do navegador. Tente recarregar a página.";
            } else if (error.name === 'NetworkError' || error instanceof TypeError) {
                msg = "Falha de rede ou configuração.";
            }
            setState(STATE.ERROR, msg);
        }
    }

    async function handleUnsubscribe() {
        setState(STATE.PROCESSING);
        try {
            const registration = await navigator.serviceWorker.ready;
            const subscription = await registration.pushManager.getSubscription();

            if (subscription) {
                const response = await fetch(urls.unsubscribe, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Accept': 'application/json',
                        'X-CSRFToken': csrfToken
                    },
                    credentials: 'same-origin',
                    cache: 'no-store',
                    body: JSON.stringify({ endpoint: subscription.endpoint })
                });

                if (response.ok) {
                    const unsubOk = await subscription.unsubscribe();
                    if (!unsubOk) {
                        throw new Error("Local unsubscribe returned false");
                    }
                    setState(STATE.PERMISSION_GRANTED_UNSUBSCRIBED);
                } else {
                    setState(STATE.ERROR, "Não foi possível remover no servidor.");
                }
            } else {
                setState(STATE.PERMISSION_GRANTED_UNSUBSCRIBED);
            }
        } catch (error) {
            setState(STATE.ERROR, "Falha ao desativar notificações.");
        }
    }

    btnMain.addEventListener('click', () => handleSubscribe(false));
    btnSecondary.addEventListener('click', handleUnsubscribe);

    init();
});
