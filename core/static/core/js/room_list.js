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
            
            let url = roomId 
                ? `/banda/relatorios/hospedagem/${window.ROOMLIST_ID}/participantes/${participantId}/alocar/`
                : `/banda/relatorios/hospedagem/${window.ROOMLIST_ID}/participantes/${participantId}/desalocar/`;
            
            let formData = new FormData();
            if (roomId) {
                formData.append('room_id', roomId);
            }
            
            fetch(url, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': csrfToken
                },
                body: formData
            })
            .then(res => res.json())
            .then(data => {
                if(data.status !== 'success') {
                    alert('Erro: ' + data.message);
                    window.location.reload();
                } else {
                    // Atualiza a badge count e lotação visualmente
                    updateRoomCounts();
                }
            })
            .catch(err => {
                console.error(err);
                alert('Erro ao processar a requisição.');
                window.location.reload();
            });
        });
    });

    function updateRoomCounts() {
        // Just reload to keep it simple and accurate for now
        window.location.reload();
    }
});
