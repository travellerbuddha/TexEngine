function r(n,f,o,i=Object.keys(n)){const e={...n};for(const t of i)JSON.stringify(o[t])!==JSON.stringify(f[t])&&(e[t]=o[t]);return e}export{r as o};
