jQuery(document).ready(function ($) {
    // Clique no botão Responder
    $(document).on('click', '.btn-responder-questao', function () {
        const btn = $(this);
        const qId = btn.data('id');
        const card = $('#questao-card-' + qId);
        const gabarito = (card.data('gabarito') || '').toUpperCase().trim();
        const selected = card.find('input[name="resposta_' + qId + '"]:checked').val();
        const feedbackDiv = $('#feedback-' + qId);
        const btnComentario = card.find('.btn-toggle-comentario');

        if (!selected) {
            alert('Selecione uma alternativa (A, B, C, D ou E) antes de responder.');
            return;
        }

        // Marca visualmente as alternativas
        card.find('.alternativa-item').removeClass('correta incorreta');

        if (selected === gabarito) {
            feedbackDiv.attr('class', 'questao-feedback correto')
                .html('<strong>✅ RESPOSTA CORRETA!</strong> Parabéns, você acertou a questão.')
                .slideDown();

            card.find('input[value="' + selected + '"]').closest('.alternativa-item').addClass('correta');
        } else {
            feedbackDiv.attr('class', 'questao-feedback incorreto')
                .html('<strong>❌ RESPOSTA INCORRETA!</strong> A alternativa correta é a <strong>Letra ' + gabarito + '</strong>.')
                .slideDown();

            card.find('input[value="' + selected + '"]').closest('.alternativa-item').addClass('incorreta');
            if (gabarito) {
                card.find('input[value="' + gabarito + '"]').closest('.alternativa-item').addClass('correta');
            }
        }

        if (btnComentario.length > 0) {
            btnComentario.fadeIn();
        }
    });

    // Clique no botão Ver Comentário da IA
    $(document).on('click', '.btn-toggle-comentario', function () {
        const qId = $(this).data('id');
        const comentarioBox = $('#comentario-' + qId);
        comentarioBox.slideToggle();
    });
});
