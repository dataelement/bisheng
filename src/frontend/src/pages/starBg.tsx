import zIndex from "@mui/material/styles/zIndex";
import { useEffect } from "react";

export default function StarBg(params) {

    useFace()

    return <canvas className=" translate-x-[-350px] translate-y-[-100px] relative" id="cccc" width="0" height="0" style={{zIndex: 999}}></canvas>
};



const useFace = () => {
    useEffect(() => {
        // var cbox = document.getElementById('cbox')
        var enter = false

        var canvas = document.getElementById('cccc');
        var ctx = canvas.getContext('2d');
        var w = canvas.width = canvas.parentNode.offsetWidth,
            h = canvas.height = 1200, //canvas.parentNode.offsetHeight,
            // var w = canvas.width = window.innerWidth,
            //     h = canvas.height = window.innerHeight,

            hue = 217,
            stars = [],
            count = 0,
            maxStars = 1400;

        // Thanks @jackrugile for the performance tip! http://codepen.io/jackrugile/pen/BjBGoM
        // Cache gradient
        var canvas2 = document.createElement('canvas'),
            ctx2 = canvas2.getContext('2d');
        canvas2.width = 100;
        canvas2.height = 100;
        var half = canvas2.width / 2,
            gradient2 = ctx2.createRadialGradient(half, half, 0, half, half, half);
        gradient2.addColorStop(0.025, '#fff');
        gradient2.addColorStop(0.1, 'hsl(' + hue + ', 61%, 33%)');
        gradient2.addColorStop(0.25, 'hsl(' + hue + ', 64%, 6%)');
        gradient2.addColorStop(1, 'transparent');

        ctx2.fillStyle = gradient2;
        ctx2.beginPath();
        ctx2.arc(half, half, half, 0, Math.PI * 2);
        ctx2.fill();

        // End cache

        function random(min, max = 0) {
            if (arguments.length < 2) {
                max = min;
                min = 0;
            }

            if (min > max) {
                var hold = max;
                max = min;
                min = hold;
            }

            return Math.floor(Math.random() * (max - min + 1)) + min;
        }

        var Star = function () {

            this.orbitRadius = random(0, w / 2.4); // random(0, w / 1.2)
            this.radius = random(100, this.orbitRadius) / 8;
            this.orbitX = w / 2;
            this.orbitY = h / 2;
            this.timePassed = random(0, maxStars);
            this.speed = random(this.orbitRadius) / 100000;
            this.alpha = random(2, 10) / 10;

            count++;
            stars[count] = this;
        }

        Star.prototype.draw = function () {
            var x = Math.sin(this.timePassed + 1) * (this.orbitRadius + (enter ? 4 : 0)) + 100 + this.orbitX,
                y = Math.cos(this.timePassed) * (this.orbitRadius + (enter ? 4 : 0)) / -1 + this.orbitY,
                twinkle = random(10);

            if (twinkle === 1 && this.alpha > 0) {
                this.alpha -= 0.05;
            } else if (twinkle === 2 && this.alpha < 1) {
                this.alpha += 0.05;
            }

            ctx.globalAlpha = this.alpha;
            ctx.drawImage(canvas2, x - this.radius / 2, y - this.radius / 2, this.radius, this.radius);
            this.timePassed += this.speed + (enter ? 0.008: 0);
        }

        for (var i = 0; i < maxStars; i++) {
            new Star();
        }

        function animation() {
            ctx.globalCompositeOperation = 'source-over';
            ctx.globalAlpha = 0.8;
            ctx.fillStyle = 'hsla(' + hue + ', 64%, 6%, 1)';
            ctx.fillRect(0, 0, w, h)

            ctx.globalCompositeOperation = 'lighter';
            for (var i = 1, l = stars.length; i < l; i++) {
                stars[i].draw();
            };

            window.requestAnimationFrame(animation);
        }

        animation()

        const func = function () {
            enter = true
        }
        const over = function () {
            enter = false
        }
        canvas.addEventListener('mouseenter', func)
        canvas.addEventListener('mouseleave', over)
        return () => {
            canvas.removeEventListener('mouseenter', func)
            canvas.removeEventListener('mouseleave', over)
        }
    }, [])
}