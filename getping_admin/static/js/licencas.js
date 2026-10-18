// Licenças específico
document.addEventListener("DOMContentLoaded", () => {
    const planoSelect = document.getElementById("tipoPlanoSelect");
    const hostsInput = document.getElementById("limiteHostsInput");
    const agentesInput = document.getElementById("limiteAgentesInput");
    const validadeSelect = document.getElementById("diasValidadeSelect");

    if (planoSelect && hostsInput && agentesInput) {
        planoSelect.addEventListener("change", (e) => {
            const plano = e.target.value;
            if (plano === "Trial") {
                hostsInput.value = 5;
                agentesInput.value = 2;
                if (validadeSelect) validadeSelect.value = "15";
            } else if (plano === "Basico") {
                hostsInput.value = 15;
                agentesInput.value = 5;
                if (validadeSelect) validadeSelect.value = "30";
            } else if (plano === "Profissional") {
                hostsInput.value = 50;
                agentesInput.value = 20;
                if (validadeSelect) validadeSelect.value = "365";
            } else if (plano === "Enterprise") {
                hostsInput.value = 200;
                agentesInput.value = 100;
                if (validadeSelect) validadeSelect.value = "365";
            }
        });
    }
});
