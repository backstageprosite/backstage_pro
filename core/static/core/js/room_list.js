document.addEventListener('DOMContentLoaded', () => {
    if (typeof Sortable !== 'undefined') {
        const dropZones = document.querySelectorAll('.drop-zone');
        dropZones.forEach(zone => {
            Sortable.create(zone, {
                group: 'shared',
                animation: 150,
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

                    let formData = new FormData();
                    if (roomId) formData.append('room_id', roomId);

                    fetch(url, {
                        method: 'POST',
                        headers: {
                            'X-CSRFToken': csrfToken,
                            'X-Requested-With': 'XMLHttpRequest'
                        },
                        body: formData
                    })
                    .then(res => {
                        if (!res.ok) throw new Error('HTTP ' + res.status);
                        return res.json();
                    })
                    .then(data => {
                        if(data.status !== 'success') {
                            alert('Erro: ' + data.message);
                            window.location.reload();
                        } else {
                            window.location.reload();
                        }
                    })
                    .catch(err => {
                        console.error(err);
                        alert('Erro na requisição: ' + err.message);
                        window.location.reload();
                    });
                }
            });
        });
    }

    // Keep HTML5 drag and drop for desktop/fallback (will not interfere if Sortable takes over correctly)
    const draggables = document.querySelectorAll('.draggable-participant');
    const dropZonesHTML5 = document.querySelectorAll('.drop-zone');

    draggables.forEach(draggable => {
        draggable.addEventListener('dragstart', () => {
            draggable.classList.add('dragging');
            draggable.setAttribute('data-dragging', 'true');
        });

        draggable.addEventListener('dragend', () => {
            draggable.classList.remove('dragging');
            draggable.removeAttribute('data-dragging');
        });
    });

    dropZonesHTML5.forEach(zone => {
        zone.addEventListener('dragover', e => {
            e.preventDefault();
            zone.classList.add('drag-over');
        });

        zone.addEventListener('dragleave', () => {
            zone.classList.remove('drag-over');
        });

        zone.addEventListener('drop', e => {
            // If Sortable handles it, it might prevent default, but just in case:
            if (typeof Sortable !== 'undefined') return;

            e.preventDefault();
            zone.classList.remove('drag-over');

            const draggable = document.querySelector('.dragging');
            if (!draggable) return;

            const participantId = draggable.dataset.participantId;
            const roomId = zone.dataset.roomId;

            zone.appendChild(draggable);

            const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]').value;
            let url = roomId ? draggable.dataset.allocateUrl : draggable.dataset.unassignUrl;

            let formData = new FormData();
            if (roomId) {
                formData.append('room_id', roomId);
            }

            fetch(url, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': csrfToken,
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: formData
            })
            .then(res => {
                if (!res.ok) throw new Error('HTTP ' + res.status);
                return res.json();
            })
            .then(data => {
                if(data.status !== 'success') {
                    alert('Erro: ' + data.message);
                    window.location.reload();
                } else {
                    window.location.reload();
                }
            })
            .catch(err => {
                console.error(err);
                alert('Erro na requisição: ' + err.message);
                window.location.reload();
            });
        });
    });
});
