document.addEventListener('DOMContentLoaded', () => {
    if (typeof Sortable !== 'undefined') {
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
});
