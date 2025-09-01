"use client"

import { useState, useEffect, useCallback, useRef } from "react"
import { Button } from "~/components"
import { Card } from "~/components/ui/Card"

interface Plant {
    id: string
    type: string
    row: number
    col: number
    health: number
    lastAction: number
}

interface Bullet {
    id: string
    row: number
    col: number
    damage: number
}

interface Zombie {
    id: string
    type: string
    row: number
    col: number
    health: number
    maxHealth: number
    speed: number
    damage: number
    lastAttack: number
}

interface Explosion {
    id: string
    row: number
    col: number
    radius: number
    damage: number
    duration: number
}

interface PlantType {
    id: string
    name: string
    cost: number
    emoji: string
    health: number
    cooldown: number
}

interface ZombieType {
    id: string
    name: string
    emoji: string
    health: number
    speed: number
    damage: number
}

export default function PlantsVsZombiesGame() {
    const [sunPoints, setSunPoints] = useState(50)
    const [selectedPlant, setSelectedPlant] = useState<string | null>(null)
    const [gameStarted, setGameStarted] = useState(false)
    const [plants, setPlants] = useState<Plant[]>([])
    const [bullets, setBullets] = useState<Bullet[]>([])
    const [zombies, setZombies] = useState<Zombie[]>([])
    const [explosions, setExplosions] = useState<Explosion[]>([])
    const [gameTime, setGameTime] = useState(0)
    const [wave, setWave] = useState(1)
    const [gameOver, setGameOver] = useState(false)
    const [gameWon, setGameWon] = useState(false)
    const [score, setScore] = useState(0)
    const [zombiesKilled, setZombiesKilled] = useState(0)
    const [isMuted, setIsMuted] = useState(false)
    const [volume, setVolume] = useState(0.5)

    // 音频引用
    const audioContextRef = useRef<AudioContext | null>(null)
    const backgroundMusicRef = useRef<HTMLAudioElement | null>(null)

    // 游戏网格 (5行9列)
    const ROWS = 5
    const COLS = 9

    const plantTypes: PlantType[] = [
        { id: "sunflower", name: "向日葵", cost: 50, emoji: "🌻", health: 100, cooldown: 3000 },
        { id: "peashooter", name: "豌豆射手", cost: 100, emoji: "🌱", health: 100, cooldown: 1500 },
        { id: "wallnut", name: "坚果墙", cost: 50, emoji: "🥜", health: 300, cooldown: 0 },
        { id: "cherrybomb", name: "樱桃炸弹", cost: 150, emoji: "🍒", health: 100, cooldown: 0 },
    ]

    const zombieTypes: ZombieType[] = [
        { id: "basic", name: "普通僵尸", emoji: "🧟", health: 100, speed: 0.02, damage: 20 },
        { id: "cone", name: "路障僵尸", emoji: "🧟‍♂️", health: 200, speed: 0.015, damage: 20 },
        { id: "bucket", name: "铁桶僵尸", emoji: "👹", health: 1300, speed: 0.01, damage: 30 },
    ]

    useEffect(() => {
        // 初始化音频上下文
        if (typeof window !== "undefined") {
            audioContextRef.current = new (window.AudioContext || (window as any).webkitAudioContext)()

            // 创建背景音乐
            backgroundMusicRef.current = new Audio()
            backgroundMusicRef.current.src = "/placeholder-music.mp3" // 占位符，实际使用时替换为真实音频文件
            backgroundMusicRef.current.loop = true
            backgroundMusicRef.current.volume = volume
        }

        return () => {
            if (audioContextRef.current) {
                audioContextRef.current.close()
            }
            if (backgroundMusicRef.current) {
                backgroundMusicRef.current.pause()
            }
        }
    }, [])

    const playSound = useCallback(
        (frequency: number, duration: number, type: OscillatorType = "sine") => {
            if (isMuted || !audioContextRef.current) return

            try {
                const oscillator = audioContextRef.current.createOscillator()
                const gainNode = audioContextRef.current.createGain()

                oscillator.connect(gainNode)
                gainNode.connect(audioContextRef.current.destination)

                oscillator.frequency.setValueAtTime(frequency, audioContextRef.current.currentTime)
                oscillator.type = type

                gainNode.gain.setValueAtTime(volume * 0.3, audioContextRef.current.currentTime)
                gainNode.gain.exponentialRampToValueAtTime(0.01, audioContextRef.current.currentTime + duration)

                oscillator.start(audioContextRef.current.currentTime)
                oscillator.stop(audioContextRef.current.currentTime + duration)
            } catch (error) {
                console.log("Audio playback failed:", error)
            }
        },
        [isMuted, volume],
    )

    const playPlantSound = useCallback(() => playSound(440, 0.2, "sine"), [playSound])
    const playShootSound = useCallback(() => playSound(800, 0.1, "square"), [playSound])
    const playExplosionSound = useCallback(() => playSound(150, 0.5, "sawtooth"), [playSound])
    const playZombieSound = useCallback(() => playSound(200, 0.3, "triangle"), [playSound])
    const playSunSound = useCallback(() => playSound(660, 0.2, "sine"), [playSound])
    const playWinSound = useCallback(() => {
        // 胜利音效序列
        setTimeout(() => playSound(523, 0.2), 0)
        setTimeout(() => playSound(659, 0.2), 200)
        setTimeout(() => playSound(784, 0.2), 400)
        setTimeout(() => playSound(1047, 0.4), 600)
    }, [playSound])
    const playLoseSound = useCallback(() => playSound(220, 1, "sawtooth"), [playSound])

    useEffect(() => {
        if (backgroundMusicRef.current) {
            backgroundMusicRef.current.volume = isMuted ? 0 : volume * 0.3

            if (gameStarted && !gameOver && !gameWon && !isMuted) {
                backgroundMusicRef.current.play().catch(console.log)
            } else {
                backgroundMusicRef.current.pause()
            }
        }
    }, [gameStarted, gameOver, gameWon, isMuted, volume])

    const explodeCherryBomb = useCallback(
        (plant: Plant) => {
            const explosion: Explosion = {
                id: `explosion-${Date.now()}-${Math.random()}`,
                row: plant.row,
                col: plant.col,
                radius: 1.5,
                damage: 150,
                duration: 1000,
            }

            setExplosions((prev) => [...prev, explosion])
            playExplosionSound() // 添加爆炸音效

            // 对范围内的僵尸造成伤害
            setZombies((prevZombies) => {
                return prevZombies.map((zombie) => {
                    const distance = Math.sqrt(Math.pow(zombie.row - plant.row, 2) + Math.pow(zombie.col - plant.col, 2))
                    if (distance <= explosion.radius) {
                        return { ...zombie, health: Math.max(0, zombie.health - explosion.damage) }
                    }
                    return zombie
                })
            })

            // 移除樱桃炸弹
            setPlants((prev) => prev.filter((p) => p.id !== plant.id))

            // 清理爆炸效果
            setTimeout(() => {
                setExplosions((prev) => prev.filter((e) => e.id !== explosion.id))
            }, explosion.duration)
        },
        [playExplosionSound],
    )

    useEffect(() => {
        if (!gameStarted || gameOver || gameWon) return

        const gameLoop = setInterval(() => {
            setGameTime((prev) => prev + 100)

            setPlants((currentPlants) => {
                const now = Date.now()
                currentPlants.forEach((plant) => {
                    if (plant.type === "sunflower" && now - plant.lastAction > 3000) {
                        setSunPoints((prev) => prev + 25)
                        playSunSound() // 添加阳光音效
                        plant.lastAction = now
                    }
                })
                return [...currentPlants]
            })

            setPlants((currentPlants) => {
                const now = Date.now()
                const newBullets: Bullet[] = []

                currentPlants.forEach((plant) => {
                    if (plant.type === "peashooter" && now - plant.lastAction > 1500) {
                        // 检查该行是否有僵尸
                        const hasZombieInRow = zombies.some((zombie) => zombie.row === plant.row && zombie.col > plant.col)
                        if (hasZombieInRow) {
                            newBullets.push({
                                id: `bullet-${Date.now()}-${Math.random()}`,
                                row: plant.row,
                                col: plant.col + 1,
                                damage: 20,
                            })
                            playShootSound() // 添加射击音效
                            plant.lastAction = now
                        }
                    }
                })

                if (newBullets.length > 0) {
                    setBullets((prev) => [...prev, ...newBullets])
                }

                return [...currentPlants]
            })

            setBullets((currentBullets) => {
                const remainingBullets: Bullet[] = []

                currentBullets.forEach((bullet) => {
                    const newCol = bullet.col + 0.3

                    // 检查子弹是否击中僵尸
                    const hitZombie = zombies.find((zombie) => zombie.row === bullet.row && Math.abs(zombie.col - newCol) < 0.5)

                    if (hitZombie) {
                        // 子弹击中僵尸，不保留子弹
                        setZombies((prevZombies) =>
                            prevZombies.map((zombie) => {
                                if (zombie.id === hitZombie.id) {
                                    const newHealth = Math.max(0, zombie.health - bullet.damage)
                                    if (newHealth === 0) {
                                        setZombiesKilled((prev) => prev + 1)
                                        setScore((prev) => prev + 10)
                                        playZombieSound() // 添加僵尸死亡音效
                                    }
                                    return { ...zombie, health: newHealth }
                                }
                                return zombie
                            }),
                        )
                    } else if (newCol < COLS) {
                        // 子弹未击中且未出界，继续移动
                        remainingBullets.push({ ...bullet, col: newCol })
                    }
                })

                return remainingBullets
            })

            setZombies((currentZombies) => {
                const now = Date.now()

                return currentZombies.map((zombie) => {
                    // 检查前方是否有植物
                    const plantInFront = plants.find(
                        (plant) => plant.row === zombie.row && Math.abs(plant.col - zombie.col) < 0.5,
                    )

                    if (plantInFront) {
                        // 攻击植物
                        if (now - zombie.lastAttack > 1000) {
                            setPlants((prevPlants) =>
                                prevPlants.map((plant) => {
                                    if (plant.id === plantInFront.id) {
                                        const newHealth = Math.max(0, plant.health - zombie.damage)
                                        // 樱桃炸弹被攻击时爆炸
                                        if (plant.type === "cherrybomb" && newHealth < plant.health) {
                                            setTimeout(() => explodeCherryBomb(plant), 100)
                                        }
                                        return { ...plant, health: newHealth }
                                    }
                                    return plant
                                }),
                            )
                            return { ...zombie, lastAttack: now }
                        }
                        return zombie
                    } else {
                        // 向前移动
                        const newCol = zombie.col - zombie.speed

                        // 检查是否到达房子
                        if (newCol <= 0) {
                            setGameOver(true)
                            playLoseSound() // 添加失败音效
                        }

                        return { ...zombie, col: newCol }
                    }
                })
            })

            setPlants((prev) => prev.filter((plant) => plant.health > 0))
            setZombies((prev) => prev.filter((zombie) => zombie.health > 0))

            if (wave >= 5 && zombies.length === 0) {
                setGameWon(true)
                playWinSound() // 添加胜利音效
            }
        }, 100)

        return () => clearInterval(gameLoop)
    }, [
        gameStarted,
        gameOver,
        gameWon,
        plants,
        zombies,
        wave,
        explodeCherryBomb,
        playShootSound,
        playSunSound,
        playZombieSound,
        playLoseSound,
        playWinSound,
    ])

    useEffect(() => {
        if (!gameStarted || gameOver || gameWon) return

        const zombieSpawner = setInterval(
            () => {
                // 限制每波僵尸数量
                const maxZombiesPerWave = Math.min(wave * 2 + 3, 15)
                if (zombies.length >= maxZombiesPerWave) return

                const randomRow = Math.floor(Math.random() * ROWS)
                const zombieTypeIndex = Math.floor(Math.random() * Math.min(wave, zombieTypes.length))
                const zombieType = zombieTypes[zombieTypeIndex]

                const newZombie: Zombie = {
                    id: `zombie-${Date.now()}-${Math.random()}`,
                    type: zombieType.id,
                    row: randomRow,
                    col: COLS - 0.5,
                    health: zombieType.health,
                    maxHealth: zombieType.health,
                    speed: zombieType.speed,
                    damage: zombieType.damage,
                    lastAttack: 0,
                }

                setZombies((prev) => [...prev, newZombie])
            },
            Math.max(4000 - wave * 300, 1500),
        ) // 随着波数增加，生成速度加快

        return () => clearInterval(zombieSpawner)
    }, [gameStarted, gameOver, gameWon, wave, zombies.length])

    useEffect(() => {
        if (!gameStarted || gameWon) return

        const waveTimer = setInterval(() => {
            if (zombies.length === 0) {
                setWave((prev) => {
                    const newWave = prev + 1
                    if (newWave > 5) {
                        setGameWon(true)
                        playWinSound() // 添加胜利音效
                    }
                    return newWave
                })
                setSunPoints((prev) => prev + 50) // 每波奖励阳光
                playSunSound() // 添加阳光奖励音效
            }
        }, 10000) // 每20秒检查一次

        return () => clearInterval(waveTimer)
    }, [gameStarted, gameWon, zombies.length, playWinSound, playSunSound])

    const plantSeed = useCallback(
        (row: number, col: number) => {
            if (!selectedPlant || col === 0) return

            const plantType = plantTypes.find((p) => p.id === selectedPlant)
            if (!plantType || sunPoints < plantType.cost) return

            // 检查该位置是否已有植物
            const existingPlant = plants.find((p) => p.row === row && p.col === col)
            if (existingPlant) return

            // 种植植物
            const newPlant: Plant = {
                id: `plant-${Date.now()}-${Math.random()}`,
                type: selectedPlant,
                row,
                col,
                health: plantType.health,
                lastAction: Date.now(),
            }

            setPlants((prev) => [...prev, newPlant])
            setSunPoints((prev) => prev - plantType.cost)
            setSelectedPlant(null)
            playPlantSound() // 添加种植音效

            if (selectedPlant === "cherrybomb") {
                setTimeout(() => explodeCherryBomb(newPlant), 1000)
            }
        },
        [selectedPlant, sunPoints, plants, plantTypes, explodeCherryBomb, playPlantSound],
    )

    const getGridContent = (row: number, col: number) => {
        const explosion = explosions.find((e) => {
            const distance = Math.sqrt(Math.pow(e.row - row, 2) + Math.pow(e.col - col, 2))
            return distance <= e.radius
        })
        if (explosion) {
            return <div className="text-red-500 text-3xl animate-ping">💥</div>
        }

        const zombie = zombies.find((z) => z.row === row && Math.floor(z.col) === col)
        if (zombie) {
            const zombieType = zombieTypes.find((zt) => zt.id === zombie.type)
            return (
                <div className="relative w-full h-full flex items-center justify-center">
                    <span className="text-2xl animate-pulse">{zombieType?.emoji}</span>
                    {/* 僵尸血量条 */}
                    <div className="absolute bottom-0 left-0 right-0 h-1 bg-gray-300 rounded">
                        <div
                            className="h-full bg-red-500 rounded transition-all"
                            style={{ width: `${(zombie.health / zombie.maxHealth) * 100}%` }}
                        />
                    </div>
                </div>
            )
        }

        // 显示植物
        const plant = plants.find((p) => p.row === row && p.col === col)
        if (plant) {
            const plantType = plantTypes.find((p) => p.id === plant.type)
            return (
                <div className="relative w-full h-full flex items-center justify-center">
                    <span className={`text-2xl ${plant.type === "cherrybomb" ? "animate-bounce" : ""}`}>{plantType?.emoji}</span>
                    {/* 血量条 */}
                    <div className="absolute bottom-0 left-0 right-0 h-1 bg-gray-300 rounded">
                        <div
                            className="h-full bg-green-500 rounded transition-all"
                            style={{ width: `${(plant.health / (plantType?.health || 100)) * 100}%` }}
                        />
                    </div>
                </div>
            )
        }

        // 显示子弹
        const bullet = bullets.find((b) => b.row === row && Math.floor(b.col) === col)
        if (bullet) {
            return <div className="text-yellow-500 text-lg animate-pulse">●</div>
        }

        return null
    }

    const resetGame = () => {
        setGameStarted(false)
        setGameOver(false)
        setGameWon(false)
        setPlants([])
        setZombies([])
        setBullets([])
        setExplosions([])
        setSunPoints(50)
        setWave(1)
        setGameTime(0)
        setScore(0)
        setZombiesKilled(0)
        setSelectedPlant(null)
    }

    return (
        <div className="min-h-screen bg-gradient-to-b from-green-400 to-green-600 p-4">
            {/* 游戏标题 */}
            <div className="text-center mb-6">
                <h1 className="text-4xl font-bold text-white mb-2 drop-shadow-lg">植物大战僵尸（灵思版）</h1>
                <p className="text-green-100">保卫你的花园！</p>
            </div>

            {gameOver && (
                <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
                    <Card className="p-8 text-center">
                        <h2 className="text-3xl font-bold text-red-600 mb-4">游戏结束！</h2>
                        <p className="text-lg mb-4">僵尸攻破了你的防线！</p>
                        <p className="mb-2">你坚持了 {wave} 波僵尸攻击</p>
                        <p className="mb-2">击杀了 {zombiesKilled} 只僵尸</p>
                        <p className="mb-6">最终得分: {score}</p>
                        <Button onClick={resetGame} className="bg-green-500 hover:bg-green-600">
                            重新开始
                        </Button>
                    </Card>
                </div>
            )}

            {gameWon && (
                <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
                    <Card className="p-8 text-center">
                        <h2 className="text-3xl font-bold text-green-600 mb-4">恭喜胜利！</h2>
                        <p className="text-lg mb-4">你成功保卫了花园！</p>
                        <p className="mb-2">完成了 {wave} 波僵尸攻击</p>
                        <p className="mb-2">击杀了 {zombiesKilled} 只僵尸</p>
                        <p className="mb-6">最终得分: {score}</p>
                        <Button onClick={resetGame} className="bg-green-500 hover:bg-green-600">
                            再玩一次
                        </Button>
                    </Card>
                </div>
            )}

            {/* 游戏界面 */}
            <div className="max-w-6xl mx-auto">
                {/* 顶部信息栏 */}
                <div className="flex justify-between items-center mb-4">
                    <div className="flex gap-4">
                        <Card className="p-4 bg-yellow-100 border-yellow-300">
                            <div className="flex items-center gap-2">
                                <span className="text-2xl">☀️</span>
                                <span className="font-bold text-lg">{sunPoints}</span>
                            </div>
                        </Card>

                        <Card className="p-4 bg-purple-100 border-purple-300">
                            <div className="flex items-center gap-2">
                                <span className="text-2xl">🌊</span>
                                <span className="font-bold text-lg">第 {wave}/5 波</span>
                            </div>
                        </Card>

                        <Card className="p-4 bg-blue-100 border-blue-300">
                            <div className="flex items-center gap-2">
                                <span className="text-2xl">🏆</span>
                                <span className="font-bold text-lg">{score}</span>
                            </div>
                        </Card>
                    </div>

                    <div className="flex gap-2 items-center">
                        <Card className="p-2 bg-gray-100 border-gray-300">
                            <div className="flex items-center gap-2">
                                <Button onClick={() => setIsMuted(!isMuted)} variant="ghost" size="sm" className="p-2">
                                    <span className="text-lg">{isMuted ? "🔇" : "🔊"}</span>
                                </Button>
                                <input
                                    type="range"
                                    min="0"
                                    max="1"
                                    step="0.1"
                                    value={volume}
                                    onChange={(e) => setVolume(Number.parseFloat(e.target.value))}
                                    className="w-16"
                                    disabled={isMuted}
                                />
                            </div>
                        </Card>

                        <Button
                            onClick={() => setGameStarted(!gameStarted)}
                            className="bg-orange-500 hover:bg-orange-600 text-white px-6 py-2"
                            disabled={gameOver || gameWon}
                        >
                            {gameStarted ? "暂停游戏" : "开始游戏"}
                        </Button>

                        <Button onClick={resetGame} className="bg-gray-500 hover:bg-gray-600 text-white px-4 py-2">
                            重置
                        </Button>
                    </div>
                </div>

                <div className="flex gap-4">
                    {/* 植物选择面板 */}
                    <Card className="p-4 bg-brown-100 border-brown-300 w-48">
                        <h3 className="font-bold mb-3 text-brown-800">选择植物</h3>
                        <div className="space-y-2">
                            {plantTypes.map((plant) => (
                                <Button
                                    key={plant.id}
                                    onClick={() => setSelectedPlant(plant.id)}
                                    disabled={sunPoints < plant.cost}
                                    className={`w-full justify-start gap-2 ${selectedPlant === plant.id ? "bg-green-500 hover:bg-green-600" : "bg-white hover:bg-gray-100"
                                        } ${sunPoints < plant.cost ? "opacity-50" : ""}`}
                                    variant={selectedPlant === plant.id ? "default" : "outline"}
                                >
                                    <span className="text-xl">{plant.emoji}</span>
                                    <div className="text-left">
                                        <div className="text-sm font-medium">{plant.name}</div>
                                        <div className="text-xs text-gray-500">{plant.cost}☀️</div>
                                    </div>
                                </Button>
                            ))}
                        </div>

                        <div className="mt-4 pt-4 border-t border-brown-300">
                            <div className="text-xs text-brown-600 space-y-1">
                                <div>植物: {plants.length}</div>
                                <div>僵尸: {zombies.length}</div>
                                <div>击杀: {zombiesKilled}</div>
                            </div>
                        </div>
                    </Card>

                    {/* 游戏战场 */}
                    <Card className="flex-1 p-4 bg-green-200 border-green-400">
                        <div className="grid grid-cols-9 gap-1 h-96">
                            {Array.from({ length: ROWS * COLS }, (_, index) => {
                                const row = Math.floor(index / COLS)
                                const col = index % COLS
                                return (
                                    <div
                                        key={index}
                                        className={`
                      border-2 border-green-300 rounded-lg flex items-center justify-center
                      cursor-pointer hover:bg-green-300 transition-colors relative
                      ${col === 0 ? "bg-green-100" : "bg-green-50"}
                      ${selectedPlant && col > 0 ? "hover:bg-yellow-200" : ""}
                    `}
                                        onClick={() => plantSeed(row, col)}
                                    >
                                        {getGridContent(row, col)}
                                    </div>
                                )
                            })}
                        </div>
                    </Card>
                </div>

                {/* 游戏说明 */}
                <Card className="mt-4 p-4 bg-blue-50 border-blue-200">
                    <h3 className="font-bold mb-2 text-blue-800">游戏说明</h3>
                    <div className="text-sm text-blue-700 space-y-1">
                        <p>• 选择植物后点击网格种植（消耗阳光）</p>
                        <p>• 向日葵每3秒产生25阳光，豌豆射手攻击僵尸</p>
                        <p>• 樱桃炸弹种植1秒后爆炸，范围攻击周围僵尸</p>
                        <p>• 坚持5波僵尸攻击即可获胜！点击音量按钮控制音效</p>
                    </div>
                </Card>
            </div>
        </div>
    )
}
