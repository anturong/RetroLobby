import os
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
import pygame

pygame.init()
font = pygame.font.Font("/usr/share/dosbox-x/SarasaGothicFixed.ttf", 110)
surf = font.render("联机大厅", True, (255, 255, 255))
pygame.image.save(surf, "/usr/share/emulationstation/themes/es-theme-carbon/art/logos/lobby.png")
print(surf.get_size())
