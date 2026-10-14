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
