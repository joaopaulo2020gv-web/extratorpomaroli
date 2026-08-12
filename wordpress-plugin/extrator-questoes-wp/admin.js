jQuery(document).ready(function ($) {
    let selectedFiles = [];
    let currentBatchId = localStorage.getItem('extrator_active_batch_id') || null;
    let pollInterval = null;
    let extractedQuestionsCache = [];

    const dropzone = $('#dropzone-lote');
    const inputFiles = $('#input-pdf-files');
    const ulFiles = $('#ul-arquivos-selecionados');
    const countFilesSpan = $('#total-arquivos-count');
    const divFilesContainer = $('#lista-arquivos-selecionados');
    const btnStartBatch = $('#btn-iniciar-lote');

    // Restaura e checa o lote mais recente do servidor ao carregar a página
    recuperarLoteAtivo();

    // Toggle do campo de modelo OCR quando checkbox é marcado/desmarcado
    $('#chk-usar-ocr').on('change', function () {
        $('#ocr-modelo-container').toggle($(this).is(':checked'));
    });

    // Drag and Drop Handlers
    dropzone.on('click', function () {
        inputFiles.click();
    });

    dropzone.on('dragover dragenter', function (e) {
        e.preventDefault();
        e.stopPropagation();
        dropzone.addClass('drag-over');
    });

    dropzone.on('dragleave drop', function (e) {
        e.preventDefault();
        e.stopPropagation();
        dropzone.removeClass('drag-over');
    });

    dropzone.on('drop', function (e) {
        const files = e.originalEvent.dataTransfer.files;
        handleFilesSelection(files);
    });

    inputFiles.on('change', function () {
        handleFilesSelection(this.files);
    });

    function handleFilesSelection(files) {
        if (!files || files.length === 0) return;

        for (let i = 0; i < files.length; i++) {
            if (files[i].type === 'application/pdf' || files[i].name.toLowerCase().endsWith('.pdf')) {
                // Evita duplicados
                if (!selectedFiles.some(f => f.name === files[i].name && f.size === files[i].size)) {
                    selectedFiles.push(files[i]);
                }
            }
        }

        renderSelectedFiles();
    }

    function renderSelectedFiles() {
        ulFiles.empty();
        countFilesSpan.text(selectedFiles.length);

        if (selectedFiles.length > 0) {
            divFilesContainer.show();
            btnStartBatch.prop('disabled', false);

            selectedFiles.forEach((file, index) => {
                const li = $(`
                    <li>
                        <span>📄 <strong>${file.name}</strong> (${(file.size / 1024 / 1024).toFixed(2)} MB)</span>
                        <button type="button" class="btn-remove-file" data-index="${index}">&times;</button>
                    </li>
                `);
                ulFiles.append(li);
            });
        } else {
            divFilesContainer.hide();
            btnStartBatch.prop('disabled', true);
        }
    }

    // Remover arquivo da lista
    ulFiles.on('click', '.btn-remove-file', function () {
        const index = $(this).data('index');
        selectedFiles.splice(index, 1);
        renderSelectedFiles();
    });

    // Salvar Configurações (API URL e Gemini Key)
    $('#form-config-extrator').on('submit', function (e) {
        e.preventDefault();
        const apiUrl = $('#config-api-url').val();
        const geminiKey = $('#config-gemini-key').val();

        $.post(extratorWPConfig.ajaxurl, {
            action: 'extrator_salvar_config',
            nonce: extratorWPConfig.nonce,
            api_url: apiUrl,
            gemini_key: geminiKey
        }, function (response) {
            if (response.success) {
                alert('✅ Configurações salvas com sucesso!');
                extratorWPConfig.apiUrl = apiUrl.replace(/\/$/, '');
                extratorWPConfig.geminiKey = geminiKey;
            } else {
                alert('❌ Erro: ' + (response.data ? response.data.message : 'Falha ao salvar.'));
            }
        });
    });

    // Submeter Lote para o Servidor Python
    $('#form-upload-lote').on('submit', function (e) {
        e.preventDefault();

        if (selectedFiles.length === 0) {
            alert('Selecione pelo menos um arquivo PDF para iniciar o lote.');
            return;
        }

        const currentApiUrl = ($('#config-api-url').val() || extratorWPConfig.apiUrl || 'http://127.0.0.1:5000').replace(/\/$/, '');
        const currentGeminiKey = $('#config-gemini-key').val() || extratorWPConfig.geminiKey || '';

        // Salva silenciosamente a configuração no WordPress para manter sincronizado
        $.post(extratorWPConfig.ajaxurl, {
            action: 'extrator_salvar_config',
            nonce: extratorWPConfig.nonce,
            api_url: currentApiUrl,
            gemini_key: currentGeminiKey
        });

        extratorWPConfig.apiUrl = currentApiUrl;
        extratorWPConfig.geminiKey = currentGeminiKey;

        const formData = new FormData();
        selectedFiles.forEach(file => {
            formData.append('pdf_files', file);
        });

        formData.append('autocorrigir_ia', $('#chk-autocorrigir-ia').is(':checked') ? 'true' : 'false');
        formData.append('usar_ocr', $('#chk-usar-ocr').is(':checked') ? 'true' : 'false');
        formData.append('provedor', 'gemini');
        formData.append('api_key', currentGeminiKey);
        formData.append('model', $('#config-ocr-model').val() || 'gemini-2.5-flash');
        formData.append('endpoint', '');
        formData.append('wp_site_url', window.location.origin);

        const targetUrl = currentApiUrl + '/api/lote/upload';

        function enviarLoteComRetry(formData, targetUrl, tentativa) {
            btnStartBatch.prop('disabled', true).text(tentativa === 1 ? '⌛ Enviando PDFs para o Servidor...' : `⌛ Acordando Servidor Render (Tentativa ${tentativa}/3)...`);
            $('#card-progresso-lote').show();
            $('#lote-status-badge').attr('class', 'badge-status pending').text(tentativa === 1 ? 'Enviando arquivos...' : 'Conectando ao servidor...');

            $.ajax({
                url: targetUrl,
                type: 'POST',
                data: formData,
                processData: false,
                contentType: false,
                timeout: 120000, // 2 minutos para suportar o aquecimento (cold start) do Render
                success: function (response) {
                    if (response.batch_id) {
                        currentBatchId = response.batch_id;
                        localStorage.setItem('extrator_active_batch_id', currentBatchId);

                        $('#lote-id-tag').text('#' + currentBatchId);
                        $('#lote-status-badge').attr('class', 'badge-status processing').text('Em Processamento');
                        btnStartBatch.text('🚀 Iniciar Processamento em Lote');

                        // Limpa lista de upload local
                        selectedFiles = [];
                        renderSelectedFiles();

                        // Inicia Polling em tempo real do progresso
                        startPollingBatchStatus(currentBatchId);
                    } else {
                        alert('❌ Resposta inválida do servidor de IA: ' + JSON.stringify(response));
                        btnStartBatch.prop('disabled', false).text('🚀 Iniciar Processamento em Lote');
                    }
                },
                error: function (xhr) {
                    if (tentativa < 3) {
                        console.warn(`[Cold Start Render] Tentativa ${tentativa} falhou. Tentando novamente em 4s...`);
                        setTimeout(function () {
                            enviarLoteComRetry(formData, targetUrl, tentativa + 1);
                        }, 4000);
                    } else {
                        let err = 'Não foi possível conectar ao servidor Python em ' + targetUrl + '. O servidor em nuvem (Render) pode estar iniciando de um estado hibernado. Por favor, aguarde alguns segundos e clique em Iniciar Processamento novamente.';
                        if (xhr.responseJSON && xhr.responseJSON.erro) {
                            err = xhr.responseJSON.erro;
                        }
                        alert('❌ Erro de Conexão: ' + err);
                        btnStartBatch.prop('disabled', false).text('🚀 Iniciar Processamento em Lote');
                    }
                }
            });
        }

        enviarLoteComRetry(formData, targetUrl, 1);
    });


    let consecutiveFailures = 0;

    function resetLoteUI() {
        if (pollInterval) clearInterval(pollInterval);
        pollInterval = null;
        localStorage.removeItem('extrator_active_batch_id');
        currentBatchId = null;
        extractedQuestionsCache = [];
        $('#card-progresso-lote').hide();
        $('#container-botao-importar').hide();
        $('#tbody-arquivos-lote').empty();
        $('#lote-progress-bar-inner').css('width', '0%').text('0%');
        $('#lote-resumo-texto').text('Processando 0 de 0 arquivos...');
        $('#lote-id-tag').text('#---');
    }

    // Botão de Limpar / Resetar Lote manualmente
    $(document).on('click', '#btn-limpar-lote', function () {
        if (confirm('Deseja limpar o progresso do lote da tela?')) {
            resetLoteUI();
        }
    });

    function startPollingBatchStatus(batchId) {
        if (pollInterval) clearInterval(pollInterval);
        consecutiveFailures = 0;

        $('#card-progresso-lote').show();
        $('#lote-id-tag').text('#' + batchId);

        function checkStatus() {
            const currentApiUrl = ($('#config-api-url').val() || extratorWPConfig.apiUrl || 'http://127.0.0.1:5000').replace(/\/$/, '');
            const statusUrl = currentApiUrl + '/api/lote/status/' + batchId + '?incluir_questoes=true';

            $.ajax({
                url: statusUrl,
                type: 'GET',
                dataType: 'json',
                timeout: 15000,
                success: function (data) {
                    consecutiveFailures = 0;
                    updateBatchProgressUI(data);

                    // Agrupa questões extraídas
                    extractedQuestionsCache = [];
                    if (data.arquivos) {
                        data.arquivos.forEach(arq => {
                            if (arq.questoes && Array.isArray(arq.questoes)) {
                                extractedQuestionsCache = extractedQuestionsCache.concat(arq.questoes);
                            }
                        });
                    }

                    if (data.status === 'concluido' || data.status === 'cancelado') {
                        if (pollInterval) clearInterval(pollInterval);
                        if (data.status === 'concluido') {
                            $('#lote-status-badge').attr('class', 'badge-status completed').text('✅ Lote Concluído!');
                        } else {
                            $('#lote-status-badge').attr('class', 'badge-status error').text('⛔ Lote Cancelado');
                        }
                        
                        if (extractedQuestionsCache.length > 0) {
                            $('#container-botao-importar').show();
                        }
                    }
                },
                error: function (xhr, textStatus, errorThrown) {
                    consecutiveFailures++;
                    console.warn(`[Lote Polling] Falha #${consecutiveFailures} ao consultar status do lote ${batchId}: HTTP ${xhr.status}`);

                    if (xhr.status === 404) {
                        // O lote expirou ou não existe mais no servidor Python (servidor reiniciou)
                        console.info('[Lote Polling] Lote não encontrado no servidor (404). Limpando estado local.');
                        resetLoteUI();
                        return;
                    }

                    // Se for falha de rede/timeout (ex: servidor Render em cold start)
                    if (consecutiveFailures <= 8) {
                        $('#lote-status-badge').attr('class', 'badge-status pending').text('⏳ Acordando Servidor Render...');
                    } else {
                        $('#lote-status-badge').attr('class', 'badge-status error').text('❌ Servidor Off-line ou Inacessível');
                    }
                }
            });
        }

        checkStatus();
        pollInterval = setInterval(checkStatus, 3000);
    }

    function recuperarLoteAtivo() {
        const apiUrl = ($('#config-api-url').val() || extratorWPConfig.apiUrl || 'http://127.0.0.1:5000').replace(/\/$/, '');
        
        // 1. Tenta por batchId salvo no LocalStorage
        if (currentBatchId) {
            // Verifica se o lote ainda existe no servidor antes de mostrar o card fixo
            $.ajax({
                url: apiUrl + '/api/lote/status/' + currentBatchId,
                type: 'GET',
                dataType: 'json',
                timeout: 10000,
                success: function (data) {
                    startPollingBatchStatus(currentBatchId);
                },
                error: function (xhr) {
                    if (xhr.status === 404) {
                        // ID no localstorage é antigo/inválido. Limpa e busca o último lote real do servidor
                        localStorage.removeItem('extrator_active_batch_id');
                        currentBatchId = null;
                        buscarUltimoLoteDoServidor(apiUrl);
                    } else {
                        // Falha temporária de conexão, tenta polling mesmo assim
                        startPollingBatchStatus(currentBatchId);
                    }
                }
            });
            return;
        }

        // 2. Se não houver no LocalStorage, consulta o lote mais recente do servidor Python
        buscarUltimoLoteDoServidor(apiUrl);
    }

    function buscarUltimoLoteDoServidor(apiUrl) {
        $.getJSON(apiUrl + '/api/lote/ultimo', function (data) {
            if (data && data.batch_id) {
                currentBatchId = data.batch_id;
                localStorage.setItem('extrator_active_batch_id', currentBatchId);
                startPollingBatchStatus(currentBatchId);
            } else {
                resetLoteUI();
            }
        }).fail(function () {
            resetLoteUI();
        });
    }

    function updateBatchProgressUI(data) {
        const total = data.total_arquivos || 0;
        const concluidos = data.concluidos || 0;
        const erros = data.erros || 0;
        const percent = total > 0 ? Math.round((concluidos / total) * 100) : 0;

        // Atualiza o badge de status dinamicamente
        if (data.status === 'na_fila') {
            $('#lote-status-badge').attr('class', 'badge-status pending').text('⌛ Na Fila do Servidor');
        } else if (data.status === 'processando') {
            $('#lote-status-badge').attr('class', 'badge-status processing').text(`⚙️ Em Processamento (${concluidos}/${total})`);
        } else if (data.status === 'concluido') {
            $('#lote-status-badge').attr('class', 'badge-status completed').text('✅ Lote Concluído!');
        } else if (data.status === 'cancelado') {
            $('#lote-status-badge').attr('class', 'badge-status error').text('⛔ Cancelado');
        }

        $('#lote-progress-bar-inner').css('width', percent + '%').text(percent + '%');
        $('#lote-resumo-texto').text(`Processados ${concluidos} de ${total} arquivos (${data.total_questoes_extraidas || 0} questões extraídas até agora)`);

        const tbody = $('#tbody-arquivos-lote');
        tbody.empty();

        if (data.arquivos && data.arquivos.length > 0) {
            data.arquivos.forEach((arq, index) => {
                let badgeClass = 'pending';
                let statusText = 'Na Fila';

                if (arq.status === 'processando') {
                    badgeClass = 'processing';
                    statusText = '⚙️ Extraindo & Corrigindo...';
                } else if (arq.status === 'concluido') {
                    badgeClass = 'completed';
                    statusText = '✅ Concluído';
                } else if (arq.status === 'erro') {
                    badgeClass = 'error';
                    statusText = '❌ Erro: ' + (arq.erro || 'Falha na extração');
                }

                const tr = $(`
                    <tr>
                        <td><strong>${index + 1}</strong></td>
                        <td>📄 ${arq.filename}</td>
                        <td><span class="badge-status ${badgeClass}">${statusText}</span></td>
                        <td><strong>${arq.total_questoes || 0}</strong> questões</td>
                        <td><span class="ia-tag">Google Gemini Flash</span></td>
                    </tr>
                `);
                tbody.append(tr);
            });
        } else {
            tbody.append(`<tr><td colspan="5" style="text-align:center; color:#888; padding:15px;">Aguardando detalhes dos arquivos do lote...</td></tr>`);
        }

        // Exibe aviso proeminente quando nenhum arquivo gerou questões
        if (data.status === 'concluido' && data.total_questoes_extraidas === 0 && total > 0) {
            $('#lote-resumo-texto').html(
                '<span style="color: #ef4444; font-weight: bold;">⚠️ Nenhuma questão foi extraída de nenhum arquivo. ' +
                'Se o PDF for digitalizado/escaneado, ative a opção <strong>"Forçar OCR via IA"</strong> no painel de upload e tente novamente.</span>'
            );
        } else if (erros > 0 && data.total_questoes_extraidas === 0) {
            $('#lote-resumo-texto').html(
                '<span style="color: #ef4444; font-weight: bold;">⚠️ Todos os arquivos falharam. Verifique as mensagens de erro acima. ' +
                'Se os PDFs forem digitalizados, ative a opção <strong>"Forçar OCR via IA"</strong>.</span>'
            );
        }
    }

    // Botão de Importar no Banco de Dados do WordPress
    $('#btn-importar-wp').on('click', function () {
        if (extractedQuestionsCache.length === 0) {
            alert('Nenhuma questão disponível no lote para importar.');
            return;
        }

        const btn = $(this);
        btn.prop('disabled', true).text('💾 Gravando no Banco do WordPress...');

        $.post(extratorWPConfig.ajaxurl, {
            action: 'extrator_importar_banco',
            nonce: extratorWPConfig.nonce,
            questoes: JSON.stringify(extractedQuestionsCache)
        }, function (response) {
            if (response.success) {
                alert('🎉 ' + response.data.message);
                btn.text('✅ Importação Concluída!');
                setTimeout(function() {
                    window.location.reload(); // Recarrega para atualizar o contador do banco no topo
                }, 1500);
            } else {
                alert('❌ Erro na importação: ' + (response.data ? response.data.message : 'Falha desconhecida.'));
                btn.prop('disabled', false).text('💾 Importar Todas as Questões no Banco do WordPress');
            }
        });
    });
});
