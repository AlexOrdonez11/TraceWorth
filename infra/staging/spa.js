// Associated only with the static behavior; API errors retain their status/body.
function handler(event) {
    var request = event.request;
    if (request.uri === '/' || request.uri.endsWith('/') ||
        request.uri.split('/').pop().indexOf('.') === -1) {
        request.uri = '/index.html';
    }
    return request;
}
