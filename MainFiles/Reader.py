# Python port of the original PHP implementation

from abc import ABC, abstractmethod


class LogReader(ABC):
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0  # bit position

    def end(self) -> bool:
        return (self.pos >> 3) >= len(self.data)

    def read_bool(self) -> int:
        if self.end():
            result = 0
        else:
            byte = self.data[self.pos >> 3]
            result = (byte >> (7 - (self.pos & 7))) & 1
        self.pos += 1
        return result

    def read_fixed(self, bits: int) -> int:
        result = 0
        while bits:
            bits -= 1
            result = (result << 1) | self.read_bool()
        return result

    def read_tally(self) -> int:
        result = 0
        while self.read_bool():
            result += 1
        return result

    def read_footer(self) -> int:
        size = self.read_fixed(2) << 3
        free = (8 - (self.pos & 7)) & 7
        size |= free

        minimum = 0
        while free < size:
            minimum += 1 << free
            free += 8

        return self.read_fixed(size) + minimum


class PlayerLogReader(LogReader, ABC):
    # Team constants
    noTeam = 0
    redTeam = 1
    blueTeam = 2

    # Flag constants
    noFlag = 0
    opponentFlag = 1
    opponentPotatoFlag = 2
    neutralFlag = 3
    neutralPotatoFlag = 4
    temporaryFlag = 5

    # Power constants
    noPower = 0
    jukeJuicePower = 1
    rollingBombPower = 2
    tagProPower = 4
    topSpeedPower = 8

    # Event hooks
    def joinEvent(self, time, newTeam): pass
    def quitEvent(self, time, oldFlag, oldPowers, oldTeam): pass
    def switchEvent(self, time, oldFlag, powers, newTeam): pass
    def grabEvent(self, time, newFlag, powers, team): pass
    def captureEvent(self, time, oldFlag, powers, team): pass
    def flaglessCaptureEvent(self, time, flag, powers, team): pass
    def powerupEvent(self, time, flag, powerUp, newPowers, team): pass
    def duplicatePowerupEvent(self, time, flag, powers, team): pass
    def powerdownEvent(self, time, flag, powerDown, newPowers, team): pass
    def returnEvent(self, time, flag, powers, team): pass
    def tagEvent(self, time, flag, powers, team): pass
    def dropEvent(self, time, oldFlag, powers, team): pass
    def popEvent(self, time, powers, team): pass
    def startPreventEvent(self, time, flag, powers, team): pass
    def stopPreventEvent(self, time, flag, powers, team): pass
    def startButtonEvent(self, time, flag, powers, team): pass
    def stopButtonEvent(self, time, flag, powers, team): pass
    def startBlockEvent(self, time, flag, powers, team): pass
    def stopBlockEvent(self, time, flag, powers, team): pass
    def endEvent(self, time, flag, powers, team): pass

    def __init__(self, data: bytes, team: int, duration: int):
        super().__init__(data)

        time = 0
        flag = self.noFlag
        powers = self.noPower
        prevent = button = block = False

        while not self.end():
            if self.read_bool():
                if team:
                    newTeam = self.noTeam if self.read_bool() else 3 - team
                else:
                    newTeam = 1 + self.read_bool()
            else:
                newTeam = team

            dropPop = self.read_bool()
            returns = self.read_tally()
            tags = self.read_tally()
            grab = (not flag) and self.read_bool()
            captures = self.read_tally()

            keep = (
                not dropPop and newTeam and
                (newTeam == team or not team) and
                (
                    not captures or
                    ((not flag and not grab) or self.read_bool())
                )
            )

            newFlag = (
                1 + self.read_fixed(2)
                if grab and keep
                else self.temporaryFlag if grab
                else flag
            )

            powerups = self.read_tally()
            powersDown = self.noPower
            powersUp = self.noPower

            i = 1
            while i < 16:
                if powers & i:
                    if self.read_bool():
                        powersDown |= i
                elif powerups and self.read_bool():
                    powersUp |= i
                    powerups -= 1
                i <<= 1

            togglePrevent = self.read_bool()
            toggleButton = self.read_bool()
            toggleBlock = self.read_bool()

            time += 1 + self.read_footer()

            if not team and newTeam:
                team = newTeam
                self.joinEvent(time, team)

            for _ in range(returns):
                self.returnEvent(time, flag, powers, team)

            for _ in range(tags):
                self.tagEvent(time, flag, powers, team)

            if grab:
                flag = newFlag
                self.grabEvent(time, flag, powers, team)

            while captures:
                captures -= 1
                if keep or not flag:
                    self.flaglessCaptureEvent(time, flag, powers, team)
                else:
                    self.captureEvent(time, flag, powers, team)
                    flag = self.noFlag
                    keep = True

            i = 1
            while i < 16:
                if powersDown & i:
                    powers ^= i
                    self.powerdownEvent(time, flag, i, powers, team)
                elif powersUp & i:
                    powers |= i
                    self.powerupEvent(time, flag, i, powers, team)
                i <<= 1

            for _ in range(powerups):
                self.duplicatePowerupEvent(time, flag, powers, team)

            if togglePrevent:
                if prevent:
                    self.stopPreventEvent(time, flag, powers, team)
                else:
                    self.startPreventEvent(time, flag, powers, team)
                prevent = not prevent

            if toggleButton:
                if button:
                    self.stopButtonEvent(time, flag, powers, team)
                else:
                    self.startButtonEvent(time, flag, powers, team)
                button = not button

            if toggleBlock:
                if block:
                    self.stopBlockEvent(time, flag, powers, team)
                else:
                    self.startBlockEvent(time, flag, powers, team)
                block = not block

            if dropPop:
                if flag:
                    self.dropEvent(time, flag, powers, team)
                    flag = self.noFlag
                else:
                    self.popEvent(time, powers, team)

            if newTeam != team:
                if not newTeam:
                    self.quitEvent(time, flag, powers, team)
                    powers = self.noPower
                else:
                    self.switchEvent(time, flag, powers, newTeam)
                flag = self.noFlag
                team = newTeam

        self.endEvent(duration, flag, powers, team)


class MapLogReader(LogReader, ABC):
    def heightEvent(self, newY): pass
    def tileEvent(self, newX, y, tile): pass

    def __init__(self, data: bytes, width: int):
        super().__init__(data)

        x = y = 0
        while not self.end() or x:
            tile = self.read_fixed(6)
            if tile:
                if tile < 6:
                    tile += 9
                elif tile < 13:
                    tile = (tile - 4) * 10
                elif tile < 17:
                    tile += 77
                elif tile < 20:
                    tile = (tile - 7) * 10
                elif tile < 22:
                    tile += 110
                elif tile < 32:
                    tile = (tile - 8) * 10
                elif tile < 34:
                    tile += 208
                elif tile < 36:
                    tile += 216
                else:
                    tile = (tile - 10) * 10

            count = 1 + self.read_footer()
            while count:
                count -= 1
                if not x:
                    self.heightEvent(y)
                self.tileEvent(x, y, tile)
                x += 1
                if x == width:
                    x = 0
                    y += 1


class SplatLogReader(LogReader, ABC):
    def splatsEvent(self, splats, timeIndex): pass

    @staticmethod
    def bits(size):
        size *= 40
        grid = size - 1
        result = 32

        if not (grid & 0xFFFF0000):
            result -= 16
            grid <<= 16
        if not (grid & 0xFF000000):
            result -= 8
            grid <<= 8
        if not (grid & 0xF0000000):
            result -= 4
            grid <<= 4
        if not (grid & 0xC0000000):
            result -= 2
            grid <<= 2
        if not (grid & 0x80000000):
            result -= 1

        offset = (((1 << result) - size) >> 1) + 20
        return result, offset

    def __init__(self, data: bytes, width: int, height: int):
        super().__init__(data)

        x_bits, x_off = self.bits(width)
        y_bits, y_off = self.bits(height)

        time = 0
        while not self.end():
            count = self.read_tally()
            if count:
                splats = []
                while count:
                    count -= 1
                    sx = self.read_fixed(x_bits) - x_off
                    sy = self.read_fixed(y_bits) - y_off
                    splats.append((sx, sy))
                self.splatsEvent(splats, time)
            time += 1
