document.addEventListener('DOMContentLoaded', () => {
    const draggables = document.querySelectorAll('.draggable-participant');
    const dropZones = document.querySelectorAll('.drop-zone');

    draggables.forEach(draggable => {
        draggable.addEventListener('dragstart', () => {
            draggable.classList.add('dragging');
            // Store the participant id
            draggable.setAttribute('data-dragging', 'true');
        });

        draggable.addEventListener('dragend', () => {
            draggable.classList.remove('dragging');
            draggable.removeAttribute('data-dragging');
        });
    });

    dropZones.forEach(zone => {
        zone.addEventListener('dragover', e => {
            e.preventDefault();
            zone.classList.add('drag-over');
        });

        zone.addEventListener('dragleave', () => {
            zone.classList.remove('drag-over');
        });

        zone.addEventListener('drop', e => {
            e.preventDefault();
            zone.classList.remove('drag-over');

            const draggable = document.querySelector('.dragging');
            if (!draggable) return;

            const participantId = draggable.dataset.participantId;
            const roomId = zone.dataset.roomId; // if empty, means unassign zone

            zone.appendChild(draggable); // optimistic UI update

            // Fetch request
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
                const contentType = res.headers.get("content-type");
                if (!contentType || !contentType.includes("application/json")) {
                    throw new TypeError("Resposta não JSON.");
                }
                return res.json();
            })
            .then(data => {
                if(data.status !== 'success') {
                    alert('Erro: ' + data.message);
                    window.location.reload();
                } else {
                    updateRoomCounts();
                }
            })
            .catch(err => {
                console.error(err);
                alert('Erro na requisição: ' + err.message);
                window.location.reload();
            });
        });
    });

    function updateRoomCounts() {
        // Just reload to keep it simple and accurate for now
        window.location.reload();
    }
});
