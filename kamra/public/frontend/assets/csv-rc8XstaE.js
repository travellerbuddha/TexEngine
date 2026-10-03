const n=/^\+\d[\d ().-]*$/;function s(e,r=!0){let t=e==null?"":String(e);return r&&/^[=+\-@\t\r]/.test(t)&&!n.test(t)&&(t=`'${t}`),/[",\n\r;]/.test(t)?`"${t.replace(/"/g,'""')}"`:t}export{s as c};
