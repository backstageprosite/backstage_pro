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
                        if (!res.ok) {
                            return res.text().then(text => {
                                try {
                                    const json = JSON.parse(text);
                                    throw new Error(json.message || 'HTTP ' + res.status);
                                } catch(e) {
                                    if (e.message.startsWith('HTTP')) throw e;
                                    throw new Error('HTTP ' + res.status + ': ' + text.substring(0, 50));
                                }
                            });
                        }
                        return res.json();
                    })
                    .then(data => {
                        if(data.status !== 'success') {
                            alert('Erro: ' + data.message);
                        }
                        window.location.reload();
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
});
