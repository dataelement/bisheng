// bisheng iframe.js 内嵌脚本
(function () {
    const iframeId = "chatbot-iframe";
    const buttonId = "chatbot-button";
    const scriptElement = document.getElementById('chatbot-iframe-script');
    const iframeUrl = scriptElement.getAttribute("data-bot-src");
    const defaultOpen = scriptElement.getAttribute("data-default-open") === "true"; // 默认打开
    const dragEnabled = scriptElement.getAttribute("data-drag") === "true"; // 按钮拖拽
    const openIcon = scriptElement.getAttribute("data-open-icon");
    const closeIcon = scriptElement.getAttribute("data-close-icon");

    // Main
    function embedChatbot() {
        // create iframe
        function createIframe() {
            const iframe = document.createElement("iframe");
            iframe.allow = "fullscreen;clipboard-write";
            iframe.id = iframeId;
            iframe.src = iframeUrl;
            iframe.style.cssText = `
          border: none; position: fixed; flex-direction: column; justify-content: space-between;
          box-shadow: rgba(150, 150, 150, 0.2) 0px 10px 30px 0px, rgba(150, 150, 150, 0.2) 0px 0px 0px 1px;
          bottom: 5rem; right: 1rem; width: 24rem; max-width: calc(100vw - 2rem); height: 40rem;
          max-height: calc(100vh - 6rem); border-radius: 0.75rem; display: flex; z-index: 2147483647;
          overflow: hidden; left: unset; background-color: #F3F4F6;
        `;

            document.body.appendChild(iframe);
        }

        // create button
        function createButton() {
            const containerDiv = document.createElement("div");
            containerDiv.id = buttonId;

            const styleSheet = document.createElement("style");
            document.head.appendChild(styleSheet);
            styleSheet.sheet.insertRule(`
          #${containerDiv.id} {
            position: fixed;
            bottom: var(--${buttonId}-bottom, 1rem);
            right: 1rem;
            left: var(--${buttonId}-left, unset);
            top: unset;
            width: 50px;
            height: 50px;
            border-radius: 25px;
            background-color: #2d4fe5;
            box-shadow: rgba(0, 0, 0, 0.2) 0px 4px 8px 0px;
            cursor: pointer;
            z-index: 2147483647;
            transition: all 0.2s ease-in-out 0s;
          }
        `);
            styleSheet.sheet.insertRule(`
          #${containerDiv.id}:hover {
            transform: scale(1.1);
          }
        `);

            // Create display div for the button icon
            const displayDiv = document.createElement("div");
            displayDiv.style.cssText =
                "display: flex; align-items: center; justify-content: center; width: 100%; height: 100%; z-index: 2147483647;background-size: cover;background-repeat: no-repeat;";
            displayDiv.style.backgroundImage = `url(${openIcon})`;
            containerDiv.appendChild(displayDiv);
            document.body.appendChild(containerDiv);

            // Add click event listener to toggle chatbot
            containerDiv.addEventListener("click", function () {
                const targetIframe = document.getElementById(iframeId);
                if (!targetIframe) {
                    createIframe();
                    resetIframePosition();
                    this.title = "Exit (ESC)";
                    displayDiv.style.backgroundImage = `url(${closeIcon})`;
                    document.addEventListener('keydown', handleEscKey);
                    return;
                }
                targetIframe.style.display = targetIframe.style.display === "none" ? "block" : "none";
                displayDiv.style.backgroundImage = `url(${targetIframe.style.display === "none" ? openIcon : closeIcon})`;

                if (targetIframe.style.display === "none") {
                    document.removeEventListener('keydown', handleEscKey);
                } else {
                    document.addEventListener('keydown', handleEscKey);
                }


                resetIframePosition();
            });

            // Enable dragging
            if (dragEnabled) {
                enableDragging(containerDiv, "both");
            }
        }

        function handleEscKey(event) {
            if (event.key === 'Escape') {
                const targetIframe = document.getElementById(iframeId);
                const button = document.getElementById(buttonId);
                if (targetIframe && targetIframe.style.display !== 'none') {
                    targetIframe.style.display = 'none';
                    button.querySelector('div').backgroundImage = `url(${openIcon})`;
                }
            }
        }
        document.addEventListener('keydown', handleEscKey);

        // Function to reset the iframe position
        function resetIframePosition() {
            const targetIframe = document.getElementById(iframeId);
            const targetButton = document.getElementById(buttonId);
            if (targetIframe && targetButton) {
                const buttonRect = targetButton.getBoundingClientRect();
                const buttonBottom = window.innerHeight - buttonRect.bottom;
                const buttonRight = window.innerWidth - buttonRect.right;
                const buttonLeft = buttonRect.left;

                // Adjust iframe position to stay within viewport
                targetIframe.style.bottom = `${buttonBottom + buttonRect.height + 5 + targetIframe.clientHeight > window.innerHeight
                        ? buttonBottom - targetIframe.clientHeight - 5
                        : buttonBottom + buttonRect.height + 5
                    }px`;

                targetIframe.style.right = `${buttonRight + targetIframe.clientWidth > window.innerWidth
                        ? window.innerWidth - buttonLeft - targetIframe.clientWidth
                        : buttonRight
                    }px`;
            }
        }

        function enableDragging(element, axis) {
            let isDragging = false;
            let startX, startY;

            element.addEventListener("mousedown", startDragging);
            document.addEventListener("mousemove", drag);
            document.addEventListener("mouseup", stopDragging);

            function startDragging(e) {
                isDragging = true;
                startX = e.clientX - element.offsetLeft;
                startY = e.clientY - element.offsetTop;
            }

            function drag(e) {
                if (!isDragging) return;

                element.style.transition = "none";
                element.style.cursor = "grabbing";

                // Hide iframe while dragging
                const targetIframe = document.getElementById(iframeId);
                if (targetIframe) {
                    targetIframe.style.display = "none";
                    element.querySelector("div").backgroundImage = `url(${openIcon})`;
                }

                const newLeft = e.clientX - startX;
                const newBottom = window.innerHeight - e.clientY - startY;

                const elementRect = element.getBoundingClientRect();
                const maxX = window.innerWidth - elementRect.width;
                const maxY = window.innerHeight - elementRect.height;

                // Update position based on drag axis
                if (axis === "x" || axis === "both") {
                    element.style.setProperty(
                        `--${buttonId}-left`,
                        `${Math.max(0, Math.min(newLeft, maxX))}px`
                    );
                }

                if (axis === "y" || axis === "both") {
                    element.style.setProperty(
                        `--${buttonId}-bottom`,
                        `${Math.max(0, Math.min(newBottom, maxY))}px`
                    );
                }
            }

            function stopDragging() {
                isDragging = false;
                element.style.transition = "";
                element.style.cursor = "pointer";
            }
        }

        // Create the chat button if it doesn't exist
        if (!document.getElementById(buttonId)) {
            createButton();
        }
    }

    document.body.onload = embedChatbot;

})();