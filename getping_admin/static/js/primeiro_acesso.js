document.addEventListener("DOMContentLoaded", () => {
            const senhaInput = document.getElementById("nova_senha");
            const reqLen = document.getElementById("req-len");
            const reqSpec = document.getElementById("req-spec");
            const reqDiff = document.getElementById("req-diff");

            function checkRequisitos() {
                const val = senhaInput.value;
                
                // 8 chars
                if (val.length >= 8) {
                    reqLen.className = "flex items-center space-x-2 text-emerald-400";
                    reqLen.querySelector("i").className = "fa-solid fa-circle-check text-[11px]";
                } else {
                    reqLen.className = "flex items-center space-x-2 text-slate-400";
                    reqLen.querySelector("i").className = "fa-regular fa-circle text-slate-600 text-[11px]";
                }

                // Especial
                if (/[^a-zA-Z0-9\s]/.test(val)) {
                    reqSpec.className = "flex items-center space-x-2 text-emerald-400";
                    reqSpec.querySelector("i").className = "fa-solid fa-circle-check text-[11px]";
                } else {
                    reqSpec.className = "flex items-center space-x-2 text-slate-400";
                    reqSpec.querySelector("i").className = "fa-regular fa-circle text-slate-600 text-[11px]";
                }

                // Diff
                if (val && val.toLowerCase() !== "administrator") {
                    reqDiff.className = "flex items-center space-x-2 text-emerald-400";
                    reqDiff.querySelector("i").className = "fa-solid fa-circle-check text-[11px]";
                } else {
                    reqDiff.className = "flex items-center space-x-2 text-slate-400";
                    reqDiff.querySelector("i").className = "fa-regular fa-circle text-slate-600 text-[11px]";
                }
            }

            senhaInput.addEventListener("input", checkRequisitos);
        });
