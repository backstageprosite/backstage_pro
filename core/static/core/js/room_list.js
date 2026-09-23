document.addEventListener('DOMContentLoaded', () => {
    const isMobile = window.innerWidth < 768;

    function getCsrfToken() {
        const input = document.querySelector('[name=csrfmiddlewaretoken]');
        if (input && input.value) return input.value;
        const cookieMatch = document.cookie.match(/csrftoken=([^;]+)/);
        return cookieMatch ? cookieMatch[1] : '';
    }

    // Desktop/Tablet drag-and-drop
    if (typeof Sortable !== 'undefined' && !isMobile) {
        const dropZones = document.querySelectorAll('.drop-zone');
        dropZones.forEach(zone => {
            Sortable.create(zone, {
                group: 'shared',
                animation: 150,
                delay: 0,
                draggable: '.draggable-participant',
                handle: '.drag-handle, .draggable-participant',
                filter: 'button, a, input, select, textarea',
                preventOnFilter: false,
                ghostClass: 'dragging-ghost',
                chosenClass: 'dragging-chosen',
                fallbackOnBody: true,
                scroll: true,
                scrollSensitivity: 80,
                scrollSpeed: 15,
                onEnd: function (evt) {
                    const draggable = evt.item;
                    const newZone = evt.to;
                    const oldZone = evt.from;

                    if (newZone === oldZone) return;

                    const participantId = draggable.dataset.participantId;
                    const roomId = newZone.dataset.roomId;

                    const csrfToken = getCsrfToken();
                    let url = roomId ? draggable.dataset.allocateUrl : draggable.dataset.unassignUrl;

                    let formData = new URLSearchParams();
                    if (roomId) formData.append('room_id', roomId);

                    fetch(url, {
                        method: 'POST',
                        headers: {
                            'X-CSRFToken': csrfToken,
                            'X-Requested-With': 'XMLHttpRequest',
                            'Content-Type': 'application/x-www-form-urlencoded'
                        },
                        body: formData.toString()
                    })
                    .then(res => {
                        window.location.reload();
                    })
                    .catch(err => {
                        console.error('Erro ao mover participante:', err);
                        window.location.reload();
                    });
                }
            });
        });
    }


    // Mobile Touch / Tap allocation
    const touchModalEl = document.getElementById('modalAlocarTouch');
    if (touchModalEl && typeof bootstrap !== 'undefined') {
        const touchModal = new bootstrap.Modal(touchModalEl);
        const form = document.getElementById('formAlocarTouch');
        const nameEl = document.getElementById('touchParticipantName');
        const selectEl = document.getElementById('touchRoomSelect');
        const titleEl = document.getElementById('touchModalActionTitle');

        document.querySelectorAll('.draggable-participant').forEach(card => {
            card.addEventListener('click', function(e) {
                // Ignore if clicked on delete/remove button or if on desktop
                if (e.target.closest('button') || window.innerWidth >= 768) {
                    return;
                }

                const name = card.querySelector('span')?.textContent.trim() || 'Integrante';
                const allocateUrl = card.dataset.allocateUrl;
                const isAlreadyInRoom = card.closest('.drop-zone')?.dataset.roomId !== '';

                if (nameEl) nameEl.textContent = name;
                if (form) form.action = allocateUrl;
                if (titleEl) titleEl.textContent = isAlreadyInRoom ? 'Mover Integrante' : 'Alocar Integrante';
                if (selectEl) selectEl.selectedIndex = 0;

                touchModal.show();
            });
        });
    }
});
