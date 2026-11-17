fetch('/api/v1/openapi.json').then(r=>r.json()).then(schema=>{
  document.getElementById('api-schema').textContent=Object.entries(schema.paths).map(([path,methods])=>
    Object.entries(methods).map(([method,definition])=>`${method.toUpperCase().padEnd(7)} ${path}\n        ${definition.summary || ''}`).join('\n')).join('\n\n');
}).catch(error=>{document.getElementById('api-schema').textContent=error.message;});
