import { useEffect, useRef } from "react";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";

export const LoginPage = ({ onLogin }) => {

    const isLoading = false
    useFace()

    const emailRef = useRef(null)
    const pwdRef = useRef(null)
    const handleLogin = (e) => {
        onLogin(emailRef.current.value, pwdRef.current.value)
    }

    return <div className="">
        <canvas id="cccc" width="0" height="0"></canvas>
        <div className="fixed z-10 w-[600px] translate-x-[-50%] left-[50%] top-[30%] pb-[100px] border rounded-lg shadow-xl flex justify-center items-center bg-[rgba(255,255,255,0.65)] dark:bg-[rgba(0,0,0,0.8)]">
            <div className="w-[60%] grid gap-6">
                <h1 className="text-xl my-[40px] text-center">文擎毕昇</h1>
                <div className="grid gap-2">
                    <div className="grid gap-1">
                        <Input
                            id="email"
                            ref={emailRef}
                            placeholder="name@example.com"
                            type="email"
                            autoCapitalize="none"
                            autoComplete="email"
                            autoCorrect="off"
                        />
                    </div>
                    <div className="grid gap-1">
                        <Input
                            id="pwd"
                            ref={pwdRef}
                            placeholder="密码"
                            type="password"
                        />
                    </div>
                    <Button disabled={isLoading} onClick={handleLogin} >登 录</Button>
                </div>
                {/* <div className="relative">
                    <div className="absolute inset-0 flex items-center">
                        <span className="w-full border-t" />
                    </div>
                    <div className="relative flex justify-center text-xs uppercase">
                        <span className="bg-background px-2 text-muted-foreground">其它方式登录</span>
                    </div>
                </div>
                <Button variant="outline" type="button" disabled={isLoading}>Github</Button> */}
            </div>
        </div>
    </div>
};


const useFace = () => {
    useEffect(() => {
        // var cbox = document.getElementById('cbox')

        var canvas = document.getElementById('cccc');
        var ctx = canvas.getContext('2d');
        // var w = canvas.width = cbox.offsetWidth,
        //     h = canvas.height = cbox.offsetHeight,
        var w = canvas.width = window.innerWidth,
            h = canvas.height = window.innerHeight,

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
            this.radius = random(100, this.orbitRadius) / 10;
            this.orbitX = w / 2;
            this.orbitY = h / 2;
            this.timePassed = random(0, maxStars);
            this.speed = random(this.orbitRadius) / 100000;
            this.alpha = random(2, 10) / 10;

            count++;
            stars[count] = this;
        }

        Star.prototype.draw = function () {
            var x = Math.sin(this.timePassed + 1) * this.orbitRadius + this.orbitX,
                y = Math.cos(this.timePassed) * this.orbitRadius / 2 + this.orbitY,
                twinkle = random(10);

            if (twinkle === 1 && this.alpha > 0) {
                this.alpha -= 0.05;
            } else if (twinkle === 2 && this.alpha < 1) {
                this.alpha += 0.05;
            }

            ctx.globalAlpha = this.alpha;
            ctx.drawImage(canvas2, x - this.radius / 2, y - this.radius / 2, this.radius, this.radius);
            this.timePassed += this.speed;
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

    }, [])
}