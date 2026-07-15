document.addEventListener("DOMContentLoaded", function() {
    // Campos que costumavam ser obrigatórios e queremos destacar se estiverem vazios
    const importantFields = ['id_title', 'id_date', 'id_city', 'id_venue'];
    
    importantFields.forEach(function(id) {
        const el = document.getElementById(id);
        if (el) {
            function checkEmpty() {
                if (!el.value.trim()) {
                    el.style.border = "2px solid #dc3545"; // Vermelho
                    el.style.backgroundColor = "#fff5f5"; // Fundo levemente avermelhado
                } else {
                    el.style.border = "";
                    el.style.backgroundColor = "";
                }
            }
            // Checa no carregamento
            checkEmpty();
            // Checa toda vez que o valor mudar ou for digitado
            el.addEventListener("input", checkEmpty);
            el.addEventListener("change", checkEmpty);
        }
    });

    // Auto-cálculo da Previsão de Chegada
    const departureTimeEl = document.getElementById('id_departure_time');
    const travelTimeEl = document.getElementById('id_travel_time');
    const arrivalTimeEl = document.getElementById('id_arrival_time');

    if (departureTimeEl && travelTimeEl && arrivalTimeEl) {
        function calculateArrival() {
            const depVal = departureTimeEl.value.trim();
            const travelVal = travelTimeEl.value.trim();

            if (!depVal || !travelVal) return;

            // Extrair horas e minutos do horário de saída
            const depMatch = depVal.match(/^(\d{1,2}):(\d{2})/);
            if (!depMatch) return;
            
            let depDate = new Date();
            depDate.setHours(parseInt(depMatch[1], 10));
            depDate.setMinutes(parseInt(depMatch[2], 10));
            depDate.setSeconds(0);

            let travelMinutes = 0;
            const tVal = travelVal.toLowerCase().replace(',', '.');
            
            // Tenta formato de relógio "HH:MM"
            const hmMatch = tVal.match(/^(\d{1,2}):(\d{2})$/);
            if (hmMatch) {
                travelMinutes = parseInt(hmMatch[1], 10) * 60 + parseInt(hmMatch[2], 10);
            } else {
                // Tenta formato de texto como "1h30", "1 hora e 30 minutos", "90m"
                const hMatch = tVal.match(/(\d+(?:\.\d+)?)\s*(?:h|hora)/);
                const mMatch = tVal.match(/(\d+(?:\.\d+)?)\s*(?:m|min)/);
                
                if (hMatch || mMatch) {
                    if (hMatch) travelMinutes += parseFloat(hMatch[1]) * 60;
                    if (mMatch) travelMinutes += parseFloat(mMatch[1]);
                } else {
                    // Se for apenas número, assume que são minutos
                    const numMatch = tVal.match(/^(\d+(?:\.\d+)?)$/);
                    if (numMatch) {
                        travelMinutes = parseFloat(numMatch[1]);
                    }
                }
            }

            // Se conseguimos calcular os minutos de deslocamento, atualiza a previsão
            if (travelMinutes > 0) {
                depDate.setMinutes(depDate.getMinutes() + travelMinutes);
                const finalH = String(depDate.getHours()).padStart(2, '0');
                const finalM = String(depDate.getMinutes()).padStart(2, '0');
                arrivalTimeEl.value = `${finalH}:${finalM}:00`;
            }
        }

        departureTimeEl.addEventListener('input', calculateArrival);
        travelTimeEl.addEventListener('input', calculateArrival);
        departureTimeEl.addEventListener('change', calculateArrival);
        travelTimeEl.addEventListener('change', calculateArrival);
    }

    // Formatação automática (Máscara) para todos os campos de Contato/Telefone
    // Busca qualquer input cujo ID termine em _contact ou _phone
    const phoneInputs = document.querySelectorAll('input[id$="_contact"], input[id$="_phone"]');
    
    phoneInputs.forEach(function(input) {
        input.addEventListener('input', function(e) {
            let v = e.target.value.replace(/\D/g, ''); // Remove tudo que não é número
            if (v.length > 11) v = v.substring(0, 11); // Limita a 11 dígitos numéricos
            
            if (v.length > 10) { // 11 dígitos: celular (XX) XXXXX-XXXX
                v = v.replace(/^(\d{2})(\d{5})(\d{4})/, '($1) $2-$3');
            } else if (v.length > 6) { // 7 a 10 dígitos: (XX) XXXX-XXXX (ou enquanto digita celular)
                v = v.replace(/^(\d{2})(\d{4})(\d{0,4})/, '($1) $2-$3');
            } else if (v.length > 2) { // 3 a 6 dígitos: (XX) XXXX
                v = v.replace(/^(\d{2})(\d{0,5})/, '($1) $2');
            } else if (v.length > 0) { // 1 a 2 dígitos: (XX
                v = v.replace(/^(\d*)/, '($1');
            }
            
            e.target.value = v;
        });
    });

    // Forçar todos os hiperlinks de campos URL no formulário a abrirem em uma nova aba
    document.querySelectorAll('.form-row a').forEach(function(link) {
        // Apenas links de verdade (ignorando ícones de calendário/relógio do Django que usam href="#")
        if (link.href && link.href.startsWith('http')) {
            link.setAttribute('target', '_blank');
        }
    });
});
