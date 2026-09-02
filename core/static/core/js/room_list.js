document.addEventListener('DOMContentLoaded', () => {
    const isMobile = window.innerWidth < 768;

    // Desktop/Tablet drag-and-drop
    if (typeof Sortable !== 'undefined' && !isMobile) {
        const dropZones = document.querySelectorAll('.drop-zone');
        dropZones.forEach(zone => {
            Sortable.create(zone, {
                group: 'shared',
                animation: 150,
                delay: 0,
                fallbackOnBody: true,
                scroll: true,
                scrollSensitivity: 80,
                scrollSpeed: 15,
                handle: '.drag-handle',
                filter: '[draggable="false"]',
                onEnd: function (evt) {
                    const draggable = evt.item;
                    const newZone = evt.to;
                    const oldZone = evt.from;

                    if (newZone === oldZone) return;

                    const participantId = draggable.dataset.participantId;
                    const roomId = newZone.dataset.roomId;

                    const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]').value;
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
                        console.error(err);
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
