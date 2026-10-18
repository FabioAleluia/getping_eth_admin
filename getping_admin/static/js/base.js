// JavaScript Base Comum
function copiarTexto(texto) {
    if (!navigator.clipboard) {
        const input = document.createElement('input');
        input.value = texto;
        document.body.appendChild(input);
        input.select();
        document.execCommand('copy');
        document.body.removeChild(input);
        alert('Copiado para a área de transferência: ' + texto);
        return;
    }
    navigator.clipboard.writeText(texto).then(() => {
        alert('Copiado para a área de transferência: ' + texto);
    }).catch(err => {
        console.error('Erro ao copiar:', err);
    });
}

document.addEventListener('click', (event) => {
    const copy = event.target.closest('[data-copy]');
    if (copy) copiarTexto(copy.dataset.copy);
    const dismiss = event.target.closest('[data-dismiss-flash]');
    if (dismiss) dismiss.parentElement.remove();
});
document.addEventListener('submit', (event) => {
    const message = event.target.dataset.confirm;
    if (message && !confirm(message)) event.preventDefault();
});
