(function () {
    window.Asc.plugin.init = function (e) {}
    window.Asc.plugin.event_onClick = function () {}
    window.Asc.plugin.button = function (id) {}

    function onMessage(e) {
        var data = e.data ? JSON.parse(e.data) : {}
        if (data.action === 'insetMarker') {
            const flag = '{{' + data.data + '}}'
            window.Asc.plugin.executeMethod('PasteText', [flag])
        }
    }

    window.addEventListener('message', onMessage, false)
})()