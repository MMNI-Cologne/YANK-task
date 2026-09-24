#########
#packages
#########

import sys, os, time, random, threading
import pandas as pd
import pygame as pg
from collections import deque
from gdx import gdx
from datetime import datetime

###########
# Constants
###########

GDX_SAMPLING_HZ = 10                 # Hz, passed to device.start()
GDX_SAMPLE_INTERVAL = 0.005          # seconds, must be < 1 / GDX_SAMPLING_HZ
GDX_CHANNELS = [1]                   # which Vernier channels to record

TRIAL_END_MARKER = [10000]           # sentinel in grip-force time series
TRIAL_START_MARKER = [20000]

GRIP_BUFFER_LEN = 1                  # only keep most recent sample for the game
TARGET_FAIL_RATE = 0.3               # aspired fail rate
BLOCK_PLAN = ["None", "left_wall", "right_wall"]

#####################################
# Global shared state (thread ↔ game)
#####################################

# Latest grip force sample from the device (updated in reader thread)
device_input_deque = deque(maxlen=GRIP_BUFFER_LEN)

# Control flags for the reader thread and trials
threading_running = True   # set to False to stop reader thread
trial_running = True       # True while a task trial is active

# Subject & task state
Sub_ID, Start, End = "", "", ""

wall = None
trial_num = -20
num_block = 1
total_reward = 0

# Wall personalization ranges (left/right easiest & hardest positions)
right_g_hardest, left_g_hardest = 0.623, 0.36
right_g_easiest, left_g_easiest = 0.95, 0.7


#################
# Device helpers
################

def restart_script():
    """
    Restart the current Python script (full process restart).

    WARNING: This discards all in-memory state. Use only for fatal errors,
    e.g. the GDX empty-buffer bug that cannot be recovered gracefully.
    """
    print("[System] Restarting whole task process...")
    time.sleep(0.2)
    os.execv(sys.executable, [sys.executable] + sys.argv)


def device_read_or_restart(device):
    """
    Wrapper around device.read() to deal with the GDX empty-buffer bug.

    If device.read() raises IndexError (observed with GDX), the script is
    restarted, because the device tends to get into an unrecoverable state.
    """
    try:
        return device.read()
    except IndexError:
        print("[Threading Process] GDX read failed (empty buffer bug). Restarting task.")
        restart_script()


def grip_device_reader():
    """
    Background thread:
    - Opens the Vernier grip device.
    - Continuously reads grip-force data.
    - Writes the latest sample into `device_input_deque` for the main thread.
    - Stores the full stream (with trial start/end markers) to disk at the end.
    """
    global threading_running, trial_running, Sub_ID

    print("[Threading Process] Started!")

    # Initialize the Vernier device
    device = gdx.gdx()
    device.open(connection="usb")
    device.select_sensors(GDX_CHANNELS)
    device.start(GDX_SAMPLING_HZ)
    print("[Threading Process] Listening for grip data...")

    # Initialize shared buffer with a zero sample so that consumers have something
    device_input_deque.append([0.0])

    # Full raw data buffer (for saving the complete force profile)
    data = []

    if not device.devices:
        print("[Threading Process] No device connected. Restarting task.")
        restart_script()

    while threading_running:
        # Trial phase: during trial_running we tag data as "during trial"
        while trial_running and threading_running:
            measurement = device_read_or_restart(device)
            device_input_deque.append(measurement)   # shared latest value
            data.append(measurement)                 # full time series log
            time.sleep(GDX_SAMPLE_INTERVAL)

        # Mark end of trial in the saved time series
        data.append(TRIAL_END_MARKER)

        # Inter-trial phase: still record, but trial_running == False
        while not trial_running and threading_running:
            measurement = device_read_or_restart(device)
            device_input_deque.append(measurement)
            data.append(measurement)
            time.sleep(GDX_SAMPLE_INTERVAL)

        # Mark start of next trial
        data.append(TRIAL_START_MARKER)

    # Clean shutdown
    device.stop()
    device.close()
    print("[Threading Process] Device closed.")

    # Save raw force profile for this subject
    subject_number_string = Sub_ID or "unknown"
    filename = f"grip_force_sub_{subject_number_string}.csv"
    full_path = os.path.join("Results", subject_number_string, "Calibration_Force_Profiles", filename)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    df_saving = pd.DataFrame(data, columns=["grip_force"])
    df_saving.to_csv(full_path, index=False)
    print("[Threading Process] Saved the force profile to", full_path)
    
########
#Classes
########

class AssetManager:
    def __init__(self):
        pg.init()  # Ensure pygame is initialized here
        self.screen_info = pg.display.Info()  # Fetch screen information
        
        assert self.screen_info.current_w == 1920
        assert self.screen_info.current_h == 1080 
                
        self.screen_width, self.screen_height = self.screen_info.current_w, self.screen_info.current_h  
        self.screen = pg.display.set_mode((self.screen_width, self.screen_height), pg.FULLSCREEN)  # Create the screen
        self.bottom_line = self.screen_height * 0.88

        self.images = {}
        self.fonts = {}
        self.colors = {}
        self.texts = {}
        
        self.load_assets ()
        
    def load_assets(self):
        # Colors
        self.colors = {
            "white": (255, 255, 255),
            "black": (0, 0, 0),
            "red": (255, 0, 0),
            "blue": (0, 0, 255),
            # Input box colors
            "input_inactive": pg.Color("lightskyblue3"),
            "input_active": pg.Color("dodgerblue2"), }

        # Fonts
        self.fonts["heading"] = pg.font.SysFont("corbel", 90, bold=True) 
        self.fonts["important"] = pg.font.SysFont("corbel", 60, bold = False)
        self.fonts["regular"] = pg.font.Font(None, 74)
        self.fonts["huge"] = pg.font.SysFont("corbel", 150, bold = True)
        self.fonts["very_important"] = pg.font.SysFont("corbel", 80, bold = True)

        # Images
        self.images["bg"] = pg.image.load("Images/Background_1920_1080_fullblue.png")
        self.images["Pizza_chief"] = pg.image.load("Images/Pizza_chief.png")
        self.Pizza_chief_width, self.Pizza_chief_height = self.images["Pizza_chief"].get_size()
        self.images["Pizza_chief_unconscious"] = pg.image.load("Images/Background_1920_1080_fullblue_unconscious.png")
        self.images["pizza"] = self.resize_image(pg.image.load("Images/Pizza.png"), 0.05)
        self.images["brick_wall"] = self.resize_image(pg.image.load("Images/pipe_bottom_small.png"), 0.05) 
        self.middle_wall_width, self.middle_wall_height = self.images["brick_wall"].get_size()
        self.images["l_wall"] = pg.image.load("Images/left_wall_10.png")
        self.images["r_wall"] = pg.image.load("Images/right_wall_10.png")
        self.images["t_wall"] = pg.image.load("Images/top_wall.png")
        self.images["ukk_logo"] = pg.image.load("Images/UKK_Logo.png")
        
        # Pre-render static text
        self.texts["welcome"] = self.render_text("Willkommen zur Studie", "heading", "black")
        self.texts["max_force"] = self.render_text("Bitte drücken Sie so fest wie möglich.", "heading", "black")
        self.texts["force_counter_current"] = self.render_text("Aktuelle Kraft:", "important", "red")
        self.texts["force_counter_max"] = self.render_text("Höchstwert:", "important", "red")
        self.texts["ready_up_1"] = self.render_text("Bitte machen Sie sich bereit.", "regular", "black")
        self.texts["ready_up_2"] = self.render_text("Der Task beginnt in wenigen Sekunden.", "regular", "black")
        self.texts["brake_text_1"] = self.render_text("Jetzt haben Sie eine kurze Pause.", "heading", "black")
        self.texts["brake_text_2"] = self.render_text("Um Fortzufahren drücken Sie bitte die Leertaste.", "regular", "black")
        self.texts["study_name"] = self.render_text("DoMoCo II", "heading", "black")
        self.texts["enter_id"] = self.render_text("Bitte ID eingeben", "important", "red")
        self.texts["success"] = self.render_text("Gewonnen", "very_important", "red")
        self.texts["pizza_counter_neu"] = self.render_text("Neuer Stand:", "important", "red")
        
    def resize_image(self, image, scale_factor): #rescales images by keeping the proportion between width and height
        width, height = image.get_size()
        new_width = int(self.screen_width * scale_factor)
        new_height = int(new_width * (height / width))
        return pg.transform.scale(image, (new_width, new_height))
    
    def render_text(self, text, font_key, color_key):
        """Render and return a text surface."""
        font = self.fonts[font_key]
        color = self.colors[color_key]
        return font.render(text, True, color)

class Chief:
    """
    Pizza chief character controlled by grip force.
    """
    DEFAULT_HORIZONTAL_SPEED = 330  # px per second

    def __init__(self, assets: AssetManager):
        """
        Pizza_chief character.

        Parameters
        ----------
        assets : AssetManager
            Shared asset manager instance from the Game (contains screen, images, fonts, etc.).
        """
        self.assets = assets

        # Sprite and dimensions
        self.image = self.assets.images["Pizza_chief"] #more efficient than calling self.assets.images["Pizza_chief"] every time
        self.width, self.height = self.image.get_size()

        # Starting position
        self.x = 0
        self.y = self.assets.bottom_line - self.height

        # Height factors (proportions of the image)
        self.top_height_factor = 1.71 / 19.05
        self.middle_height_factor = 5.14 / 19.05
        self.bottom_height_factor = 12.20 / 19.05

        # Create subsurfaces for each part
        self.image_top = self.image.subsurface((0, 0, self.width, self.height * self.top_height_factor))
        self.image_middle = self.image.subsurface((0, self.height * self.top_height_factor,  self.width, self.height * self.middle_height_factor))
        self.image_bottom = self.image.subsurface((0, self.height * (self.top_height_factor + self.middle_height_factor), self.width, self.height * self.bottom_height_factor))
        
        # Bounding rects for each part
        self.top_bounding_rect = self.image_top.get_bounding_rect()
        self.middle_bounding_rect = self.image_middle.get_bounding_rect()
        self.bottom_bounding_rect = self.image_bottom.get_bounding_rect()

    def get_rects(self):
        """Return Rect objects for each part of Pizza_chief."""
        top_rect = pg.Rect(
            self.x + self.top_bounding_rect.x,
            self.y,
            self.top_bounding_rect.width,
            self.top_bounding_rect.height, )
        middle_rect = pg.Rect(
            self.x + self.middle_bounding_rect.x,
            self.y + self.height * self.top_height_factor,
            self.middle_bounding_rect.width,
            self.middle_bounding_rect.height, )
        bottom_rect = pg.Rect(
            self.x + self.bottom_bounding_rect.x,
            self.y + self.height * (self.top_height_factor + self.middle_height_factor),
            self.bottom_bounding_rect.width,
            self.bottom_bounding_rect.height, )
        
        return top_rect, middle_rect, bottom_rect

    def draw(self, screen): #at the moment not strictly necessary, but if effects should be added way easier within a function
        """Draw Pizza_chief."""
        screen.blit(self.image, (self.x, self.y))

    def update(self, dt):
        """Update Pizza_chief’s position based on grip force."""
        global scaling_factor_max_force

        # Vertical movement based on grip force
        grip_force = device_input_deque[-1]
        self.y = (
            self.assets.bottom_line
            - self.height
            - (grip_force[0] * scaling_factor_max_force))

        # Horizontal movement
        self.x += Chief.DEFAULT_HORIZONTAL_SPEED * dt

class Game:
    def __init__(self):
        pg.init()
        self.assets = AssetManager()
        self.clock = pg.time.Clock()

        self.dict_results = {}
        self.subject_id = ""

        # Trial-level data within a block
        self.dict_results = {'Sub_ID' : [], 'Type': [], 'Block' : [], 'Trial_Num' : [], 'Trial_Outcome' : [],
                'Start' : [], 'End' : [], 'Fail_Location': [], 'Max_Grip' : [], 'L_Wall_Pos' : [], 'R_Wall_Pos' : []}
        # Success/fail tracking for wall personalization
        self.dict_outcome = {"left_wall": {}, "right_wall": {}, "final_settings": {}}

    def store_information(self, Sub_ID = "", Type = "", Block = "", Trial_Num = "", Trial_Outcome = "",
                          Start = "", End = "", Fail_Location = "", Max_Grip = "", L_Wall_Pos = "", R_Wall_Pos = ""):
        """
        Append trial-level information to the result dictionary.
        
        This function collects all relevant metadata from the task
        (subject ID, block number, trial number, trial outcome, timestamps,
        wall positions, etc.) and appends each field to the corresponding
        list inside `self.dict_results`. Missing or unused fields can be
        left as empty strings.
        
        Parameters
        ----------
        Sub_ID : str, optional
            Participant identifier.
        Type : str, optional
            Type of action happening (Max grip estimation, Trial, etc.)
        Block : str or int, optional
            Block number of the task in which this trial occurred.
        Trial_Num : str or int, optional
            Trial counter within or across blocks.
        Trial_Outcome : int, optional
            Fail = 0, Success = 1, "" = no trial information stored
        Start : float or str, optional
            Timestamp at trial start (e.g., time.time()).
        End : float or str, optional
            Timestamp when the trial ended.
        Fail_Location : str, optional
            The wall or obstacle causing the failure ("left", "right", "middle", or "").
        Max_Grip :float, optional
            Maximum grip force out of three trials
        L_Wall_Pos : float or str, optional
            Left wall position used in this trial.
        R_Wall_Pos : float or str, optional
            Right wall position used in this trial.
        
        Notes
        -----
        - All keys in `self.dict_results` must match the keys used here.
        - Values are appended in parallel, creating row-aligned lists that can
          later be saved as a CSV where each index corresponds to one trial.
        - Fields that are unused for a given call should be left as empty strings.
        
        """
        
        info = {"Sub_ID": Sub_ID, "Type": Type, "Block": Block, "Trial_Num": Trial_Num, "Trial_Outcome": Trial_Outcome,
                "Start": Start, "End": End, "Fail_Location": Fail_Location, 
                "Max_Grip" : Max_Grip, "L_Wall_Pos": L_Wall_Pos, "R_Wall_Pos": R_Wall_Pos , }
        
        for key, value in info.items():
            self.dict_results[key].append(value)
            
        

    def introduction(self):
        """Handles the introduction screen where Subject ID is entered."""
        global threading_running, trial_running, Sub_ID, Start, End
        
        Start = datetime.now().strftime("%d/%m/%Y %H:%M:%S.%f")
        
        input_box = pg.Rect(
        self.assets.screen_width * 0.5 - 100,
        self.assets.screen_height * 0.75,
        self.assets.screen_width * 0.3,
        self.assets.screen_height * 0.05, )
        
        color_inactive = self.assets.colors["input_inactive"]
        color_active = self.assets.colors["input_active"]
        color = color_inactive
        active = False
        text = ""
        done = False
        
        
        while not done: 
            for event in pg.event.get():
                if event.type == pg.QUIT or (event.type == pg.KEYDOWN and event.key == pg.K_ESCAPE):
                    done = True
                    trial_running = False
                    threading_running = False
                    self.save()
                    pg.quit()
                    sys.exit()

                if event.type == pg.MOUSEBUTTONDOWN:
                    active = input_box.collidepoint(event.pos)
                    color = color_active if active else color_inactive

                if event.type == pg.KEYDOWN and active:
                    if event.key == pg.K_RETURN:
                        self.subject_id = text
                        self.create_folder(f"Results/{self.subject_id}")
                        text = ""
                        done = True
                        Sub_ID = self.subject_id 
                    elif event.key == pg.K_BACKSPACE:
                        text = text[:-1]
                    else:
                        text += event.unicode

            self.assets.screen.fill(self.assets.colors["white"])
            self.assets.screen.blit(self.assets.images["ukk_logo"], (self.assets.screen_width * 0.5 - self.assets.images["ukk_logo"].get_width() / 2, 0))
            self.assets.screen.blit(self.assets.texts["welcome"], (self.assets.screen_width * 0.5 - self.assets.texts["welcome"].get_width() / 2, self.assets.screen_height * 0.3)) 
            self.assets.screen.blit(self.assets.texts["study_name"], (self.assets.screen_width * 0.5 - self.assets.texts["study_name"].get_width() / 2, self.assets.screen_height * 0.4))
            self.assets.screen.blit(self.assets.texts["enter_id"], (self.assets.screen_width * 0.5 - self.assets.texts["study_name"].get_width() / 2, self. assets.screen_height * 0.8))
            
            txt_surface = self.assets.fonts["regular"].render(text, True, color)
            input_box.w = max(200, txt_surface.get_width() + 10)
            self.assets.screen.blit(txt_surface, (input_box.x + 5, input_box.y + 5))
            pg.draw.rect(self.assets.screen, color, input_box, 2)

            pg.display.flip()
            self.clock.tick(60)

        End = datetime.now().strftime("%d/%m/%Y %H:%M:%S.%f")
        self.store_information(Sub_ID = Sub_ID, Type = "Introduction", Block = "", Trial_Num = "", Trial_Outcome = "",
                              Start = Start, End = End, Fail_Location = "", Max_Grip = "", L_Wall_Pos = "", R_Wall_Pos = "")
        
    def max_force_test(self):
        """
        Measure the participant's maximum grip force (3 repetitions),
        compute the overall maximum, and derive a scaling factor to map
        grip force to Pizza_chief's jump height.
        """
        global threading_running, trial_running, Start, End
        
        Start = datetime.now().strftime("%d/%m/%Y %H:%M:%S.%f") 
        print("Testing the maximum force")

        def calculate_scaling_factor(maximum_force: float) -> None:
            """
            Calculate factor to scale grip force to Pizza_chief's height.

            Target:
                Half of the maximum grip force should move Pizza_chief
                just above the pipe (middle wall).
            """
            global scaling_factor_max_force

            jump_height = self.assets.Pizza_chief_height + self.assets.middle_wall_height
            scaling_factor_max_force = jump_height / (maximum_force / 2)
            
            print("Scaling factor max force calibration:", scaling_factor_max_force)

        def test_repetition() -> float:
            """
            Run one max-grip repetition (about 5 seconds),
            show current and maximal force on screen,
            and return the maximal force of this repetition.
            """
            global threading_running, trial_running

            maximum_force = 0.0
            done = False
            counter = -5.0
            last_time = pg.time.get_ticks()

            while not done:
                # Handle abort
                for event in pg.event.get():
                    if event.type == pg.QUIT or (
                        event.type == pg.KEYDOWN and event.key == pg.K_ESCAPE):
                        threading_running = False
                        trial_running = False
                        self.save()
                        pg.quit()
                        sys.exit()

                # Simple 5 s timer
                now = pg.time.get_ticks()
                dt = (now - last_time) / 1000
                last_time = now
                counter += dt
                if counter > 0:
                    done = True

                # Background and static texts
                self.assets.screen.fill(self.assets.colors["white"])
                self.assets.screen.blit(self.assets.images["ukk_logo"], (self.assets.screen_width * 0.5 - self.assets.images["ukk_logo"].get_width() / 2 ,0, ) , )
                self.assets.screen.blit(self.assets.texts["max_force"], (self.assets.screen_width * 0.5 - self.assets.texts["max_force"].get_width() / 2, self.assets.screen_height * 0.3, ) , )
                self.assets.screen.blit(self.assets.texts["force_counter_current"], ( self.assets.screen_width * 0.4- self.assets.texts["force_counter_current"].get_width() / 2, self.assets.screen_height * 0.45, ), )
                self.assets.screen.blit(self.assets.texts["force_counter_max"], (self.assets.screen_width * 0.4 - self.assets.texts["force_counter_max"].get_width() / 2, self.assets.screen_height * 0.64, ) , )

                # Update current and maximum force
                current_force = round(device_input_deque[-1][-1], 2)
                maximum_force = round(max(maximum_force, current_force), 2)

                # Render current / maximal force values
                text_current_force = self.assets.fonts["huge"].render(f"{current_force}", True, self.assets.colors["red"])
                text_max_force = self.assets.fonts["huge"].render(f"{maximum_force}", True, self.assets.colors["red"])

                # Draw the numbers
                self.assets.screen.blit( text_current_force, (self.assets.screen_width * 0.6, self.assets.screen_height * 0.40) , )
                self.assets.screen.blit(text_max_force, (self.assets.screen_width * 0.6, self.assets.screen_height * 0.60) , )

                pg.display.update()
                time.sleep(0.005)  # keep below device sampling interval

            return maximum_force

        # --- Run three repetitions with short breaks in between ---

        maximum_force_1 = test_repetition()

        # Short pause after repetition 1
        self.brake()
        maximum_force_2 = test_repetition()

        # Short pause after repetition 2
        self.brake()
        maximum_force_3 = test_repetition()

        # Overall maximum across the three attempts
        maximum_force = round( max( maximum_force_1, maximum_force_2, maximum_force_3), 2) 
        print(f"Maximum force over 3 repetitions: {maximum_force}")

        # Derive scaling factor used later to map grip → height
        calculate_scaling_factor(maximum_force)
        print("The maximum force was:", maximum_force)

        # Final "get ready" screen before the actual task starts
        pause = True
        counter2 = -10.0
        last_time2 = pg.time.get_ticks()
        while pause:
            now2 = pg.time.get_ticks()
            dt2 = (now2 - last_time2) / 1000
            last_time2 = now2
            counter2 += dt2

            for event in pg.event.get():
                if event.type == pg.QUIT or (event.type == pg.KEYDOWN and event.key == pg.K_ESCAPE):
                    threading_running = False
                    trial_running = False
                    pg.quit()
                    sys.exit()

            if counter2 >= 0:
                pause = False

            self.assets.screen.fill(self.assets.colors["white"])
            self.assets.screen.blit(self.assets.images["ukk_logo"], (self.assets.screen_width * 0.5 - self.assets.images["ukk_logo"].get_width() / 2, 0,) , )
            self.assets.screen.blit(self.assets.texts["ready_up_1"], (self.assets.screen_width * 0.5- self.assets.texts["ready_up_1"].get_width() / 2, self.assets.screen_height * 0.3, ) , )
            self.assets.screen.blit( self.assets.texts["ready_up_2"], (self.assets.screen_width * 0.5 - self.assets.texts["ready_up_2"].get_width() / 2, self.assets.screen_height * 0.5, ) , )
            pg.display.update()
        
        End = datetime.now().strftime("%d/%m/%Y %H:%M:%S.%f")
        self.store_information(Sub_ID = "", Type = "Max_Grip", Block = "", Trial_Num = "", Trial_Outcome = "",
                              Start = Start, End = End, Fail_Location = "", Max_Grip = maximum_force, L_Wall_Pos = "", R_Wall_Pos = "")

        return maximum_force

    def single_wall(self):
        
        """
        Select the next set of wall positions for one side ("left_wall" or "right_wall").
    
        High-level behaviour
        --------------------
        - For the very first block (num_block == 1, trial_num < 0), use a predefined
          sequence of wall positions that spans the full range from hardest to easiest.
        - For later blocks (num_block > 1, trial_num < 0), use a reduced familiarisation
          set of positions around the current range.
        - Once enough trials have been collected (trial_num >= 0), estimate for each
          wall position the fail rate based on self.dict_outcome[wall] and derive a
          new interval of wall positions around the desired fail rate (~0.3, i.e. 70%
          success). Sample the next block within this interval.
        - If no acceptable setting can be found (always too easy / too hard), fall back
          to the easiest setting and mark the personalisation for this wall as finished.
    
        Parameters
        ----------
        wall : str
            Which wall is currently being personalised ("left_wall" or "right_wall").
    
        Returns
        -------
        adjusted_wall_positions : list[float] or None
            Positions for the wall that is currently being personalised.
            None if this wall is finished and we should move on.
        other_wall_positions : list[float] or None
            Positions for the opposite wall.
        """
        global trial_num, num_block, Start, End, wall
        
        Start = datetime.now().strftime("%d/%m/%Y %H:%M:%S.%f")
        # If this wall has already been finalised in a previous call,
        # signal that no more trials are needed for this wall.
        if wall in self.dict_outcome["final_settings"] or (num_block == 1 and trial_num == 0):
            return None, None

        # ---- Bookkeeping containers for the adaptive phase ----
        fail_rates = {}      # fail_rates[level] = fail rate at this wall position
        trial_counts = []    # number of trials per level, in the same order as levels[]
        thresholds = []      # per-level threshold, in the same order as levels[]
        
        # Variables that will be set later
        upper_wall_position = None
        lower_wall_position = None
        adjusted_wall_positions = None
        other_wall_positions = None
        more_samples = None  # used when fail rate == threshold and more data are needed
        
        # Map global wall ranges to "adjusted" wall (a_*) and "other" wall (o_*)
        # a_*  = wall currently being personalised (left or right)
        # o_*  = opposite wall in the same trials
        if wall == "left_wall":
            a_easiest, a_hardest = left_g_easiest, left_g_hardest
            o_easiest, o_hardest = right_g_easiest, right_g_hardest
        else:
            a_easiest, a_hardest = right_g_easiest, right_g_hardest
            o_easiest, o_hardest = left_g_easiest, left_g_hardest
        
        print("easiest, hardest: ", a_easiest, a_hardest, o_easiest, o_hardest)
        
        # ------------------------------------------------------------------
        # 1) Familiarisation phases: no adaptation, just predefined patterns
        # ------------------------------------------------------------------
        if num_block == 1:
            # First block: span the full range from easiest to hardest (20 trials)
            adjusted_wall_positions = (
                [a_easiest] * 12
                + [round(a_easiest - (a_easiest - a_hardest) * 0.25, 3)] * 2
                + [round(a_easiest - (a_easiest - a_hardest) * 0.40, 3)] * 2
                + [round(a_easiest - (a_easiest - a_hardest) * 0.50, 3)] * 2
                + [a_hardest] * 2)
            other_wall_positions = (
                [o_easiest] * 2
                + [round(o_easiest - (o_easiest - o_hardest) * 0.25, 3)] * 2
                + [round(o_easiest - (o_easiest - o_hardest) * 0.40, 3)] * 2
                + [round(o_easiest - (o_easiest - o_hardest) * 0.50, 3)] * 2
                + [o_hardest] * 2
                + [o_easiest] * 10)
        
        elif num_block >= 1 and trial_num < 0:
            # Later blocks: get first 10 Trials for left and right wall
            adjusted_wall_positions = (
                [a_easiest]  # just once
                + [round(a_easiest - (a_easiest - a_hardest) * 0.25, 3)] * 3
                + [round(a_easiest - (a_easiest - a_hardest) * 0.40, 3)] * 3
                + [round(a_easiest - (a_easiest - a_hardest) * 0.50, 3)] * 3)
            other_wall_positions = [o_easiest] * 10            
        
        # ------------------------------------------------------
        # 2) Adaptive phase: use past success/fail information
        # ------------------------------------------------------
        else:
            # --- compute success/fail rates per wall position ---
            levels = list(self.dict_outcome[wall].keys())
            levels.sort()  # sorted from hardest (small value) to easiest (large value)
        
            TARGET_FAIL_RATE = 0.3
        
            for i, lvl in enumerate(levels):
                # Fail rate at this level: 1 - success_rate
                outcome = self.dict_outcome[wall][lvl]
                fail_rate = 1 - sum(outcome) / len(outcome)
                fail_rate = round(fail_rate, 3)
                fail_rates[lvl] = fail_rate
        
                # Number of trials at this level
                n_trials = len(outcome)
                trial_counts.append(n_trials)
        
                # Determine the closest "achievable" threshold to the target fail rate,
                # given the current number of samples at this level.
                # The thresholds list is indexed in the same order as levels[].
                for l in range(trial_counts[i]):
                    # For l=0: 1/(l+1) = 1.0 → never < 0.3, so the branch below is safe.
                    current_level = 1 / (l + 1)
        
                    # Exact match to desired fail rate
                    if current_level == TARGET_FAIL_RATE:
                        thresholds.append(TARGET_FAIL_RATE)
                        break
        
                    # As soon as 1/(l+1) drops below the target, decide whether this
                    # or the previous value (1/l) is closer to the target.
                    elif current_level < TARGET_FAIL_RATE:
                        prev_level = 1 / l  # safe because l >= 1 here
                        if abs(current_level - TARGET_FAIL_RATE) < abs(prev_level - TARGET_FAIL_RATE):
                            thresholds.append(round(current_level, 3))
                        else:
                            thresholds.append(round(prev_level, 3))
                        break
        
                    # If we reach the last possible l and still have no threshold,
                    # fall back to 1/n_trials as the best we can do.
                    if (l + 1) == trial_counts[i] and len(thresholds) < i + 1:
                        thresholds.append(round(1 / trial_counts[i], 3))
        
            print("dict rates: ", fail_rates)
            print("length: ", trial_counts, "\nthresholds: ", thresholds)
        
            # -----------------------------
            # define new range of positions
            # -----------------------------
            for i, level in enumerate(levels):
                # Find the first level (from hardest to easiest) where fail_rate <= threshold
                if fail_rates[level] <= thresholds[i]:
                    # Case A: not at the easiest level yet → check neighbour level
                    if level != levels[-1]:
                        # Check if the next easier level also passes its threshold
                        # to avoid "lucky shot" on a single level.
                        if fail_rates[levels[i + 1]] <= thresholds[i + 1]:
                            dist = levels[i + 1] - level  # distance between two consecutive levels
        
                            # Fast progression if both levels have 0% fail rate:
                            # minimal lower_wall_position = 5% into the range.
                            if fail_rates[levels[i + 1]] == 0 and fail_rates[level] == 0:
                                lower_wall_position = level + 0.05 * dist
        
                            # If the threshold achieved at this level is exactly the
                            # best possible (equal to fail rate), oversample around it.
                            elif thresholds[i] == fail_rates[level]:
                                more_samples = level  # mark this level for denser sampling
        
                                # Upper wall: go half the distance towards the next harder level,
                                # or towards global hardest if this is the very first level.
                                if i != 0:
                                    upper_wall_position = levels[i] - abs(levels[i] - levels[i - 1]) * 0.5
                                else:
                                    upper_wall_position = levels[i] - abs(levels[i] - o_hardest) * 0.5
        
                                # Lower wall: half-way towards the next easier level,
                                # or half-way towards a_easiest if already at the easiest.
                                if i != len(levels) - 1:
                                    lower_wall_position = levels[i] + abs(levels[i + 1] - levels[i]) * 0.5
                                else:
                                    lower_wall_position = levels[i] + abs(a_easiest - levels[i]) * 0.5
        
                                break
        
                            # Standard case: use the next easier level as lower bound
                            else:
                                lower_wall_position = levels[i + 1]
        
                            # Set upper bound if possible: one level harder if it exists
                            if i - 1 > 0 and upper_wall_position is None:
                                upper_wall_position = levels[i - 1]
                                break
                            else:
                                if upper_wall_position is None:
                                    # If even the hardest tested position was too easy,
                                    # set the global hardest as new upper level.
                                    upper_wall_position = a_hardest
                                    break
        
                        else:
                            # "Lucky shot" of harder wall position → continue searching
                            pass
        
                    # Case B: we are at the easiest level
                    else:
                        # When performance is poor, only sample between the easiest levels.
                        lower_wall_position = a_easiest
                        # If there is a harder level before this one, use it as upper bound.
                        upper_wall_position = levels[i - 1]
                        break
        
                # If we reach the easiest level without ever finding an acceptable fail rate,
                # make the task as easy as possible.
                if level == levels[-1] and lower_wall_position is None:
                    lower_wall_position = a_easiest
        
                    # If even the easiest level has a high fail rate after many trials,
                    # consider the participant too unskilled for this wall.
                    adjusted_wall_positions = [a_easiest] * 10
                    if trial_counts[-1] > 10 and fail_rates[levels[-1]] > 0.4:
                        self.dict_outcome["final_settings"][wall] = a_easiest
                        if num_block == 3:
                            return None, None
        
                    other_wall_positions = [o_easiest] * 12
                    return adjusted_wall_positions, other_wall_positions
        
            print("upper wall position: ", upper_wall_position,
                  "\nlower wall position: ", lower_wall_position,
                  "\nsample again (more_samples): ", more_samples)  # Keep for evaluation
            
            # ----------------------------------------
            # Clamp interval to calibrated range
            # ----------------------------------------
            # We never want to go harder than a_hardest or easier than a_easiest.
            if upper_wall_position is not None and lower_wall_position is not None:
                upper_wall_position = max(a_hardest, min(upper_wall_position, a_easiest))
                lower_wall_position = max(a_hardest, min(lower_wall_position, a_easiest))
            
            print("upper wall position (clamped): ", upper_wall_position,
                  "\nlower wall position (clamped): ", lower_wall_position)
        
            # ----------------------------------------
            # define new interval for future sampling
            # ----------------------------------------
            range_wall = round(lower_wall_position - upper_wall_position, 2)
        
            if range_wall <= 0.01:
                # Range is very narrow → treat as final setting for this wall.
                steps = "no steps final position reached"
                #trial_num = -20
                final_level = round((lower_wall_position + upper_wall_position) / 2, 3)
                adjusted_wall_positions = [final_level] * 10
                self.dict_outcome["final_settings"][wall] = [final_level]
        
            else:
                # Split the range into three equal steps and sample symmetrically
                steps = round(range_wall / 3, 3)
                adjusted_wall_positions = (
                    [lower_wall_position] * 3
                    + [lower_wall_position - steps] * 3
                    + [upper_wall_position + steps] * 3
                    + [upper_wall_position] * 3
                )
        
            print(
                "upper", upper_wall_position,
                "lower", lower_wall_position,
                "range", range_wall,
                "steps", steps
            )
        
        # If we did not set other_wall_positions explicitly above, default to easiest.
        if other_wall_positions is None:
            other_wall_positions = [o_easiest] * 12
            random.shuffle(adjusted_wall_positions)
            random.shuffle(other_wall_positions)
        
        # For later blocks, ensure we have dict_outcome entries for all levels we now sample.
        if num_block > 1:
            for level in set(adjusted_wall_positions):
                if level not in self.dict_outcome[wall].keys():
                    self.dict_outcome[wall][level] = []
        
        End = datetime.now().strftime("%d/%m/%Y %H:%M:%S.%f")
        self.store_information(Sub_ID = "" , Type = "Single_Wall", Block = num_block, Trial_Num = trial_num, Trial_Outcome = "",
                              Start = Start, End = End, Fail_Location = "", Max_Grip = "", L_Wall_Pos = adjusted_wall_positions, R_Wall_Pos = other_wall_positions)
        
        return adjusted_wall_positions, other_wall_positions
       
    def task(self) -> None:
        """
        Run one block of the task (consisting of several trials).

        Behaviour depends on the current block (global num_block):
        - Block 1: personalise left wall.
        - Block 2: primarily left wall; if left_wall cannot be adjusted (returns None)
                   and trial_num < 0, fall back to right wall.
        - Block 3: personalise right wall (using self.dict_outcome from previous blocks).

        Blocks >= 4 are currently not used.
        """
    
        # Import the global running variable
        global threading_running, trial_running, trial_num, num_block, Start, End
        
        self.dict_succes = {}
 
        trial = True
        
        while trial:
        #     # ----------------------------------------------------------
        #     # 1. Get wall positions, or move on to next wall adaptation
        #     # ----------------------------------------------------------            
            adjusted_wall_positions, other_wall_positions = self.single_wall()
            if adjusted_wall_positions is None and other_wall_positions is None:
                trial = False
                break
           #     # --------------------------------------------------
           #     # 2. Run one trial per pair of wall positions
           #     # --------------------------------------------------
            for n, (adjusted_position, other_position) in enumerate(
                zip(adjusted_wall_positions, other_wall_positions)):
                Start = datetime.now().strftime("%d/%m/%Y %H:%M:%S.%f")
                trial_num += 1
                print(f"Trial {trial_num}: adjusted = {adjusted_position}, other = {other_position}")
     
                # Create a new Pizza_chief for this trial
                Pizza_chief = Chief(self.assets)
     
                # Map adjusted/other position to left or right wall
                if wall == "left_wall":
                    left_position = adjusted_position
                    right_position = other_position
                else:
                    left_position = other_position
                    right_position = adjusted_position
     
                # -----------------------------
                # 2a. Draw the initial scenery
                # -----------------------------
                self.assets.screen.blit(self.assets.images["bg"], (0, 0))
                self.assets.screen.blit(self.assets.images["t_wall"],
                                        (self.assets.screen_width * 0.2, self.assets.screen_height * 0.0) , )
                self.assets.screen.blit(self.assets.images["l_wall"],
                                        (-self.assets.screen_width * left_position, self.assets.screen_height * 0.5),)
                self.assets.screen.blit(self.assets.images["r_wall"],
                                        (self.assets.screen_width * right_position, -self.assets.screen_height * 0.1) , )
                self.assets.screen.blit(self.assets.images["brick_wall"],
                                        (self.assets.screen_width * 0.5, self.assets.bottom_line - self.assets.middle_wall_height) , )
     
                # Capture initial screen for countdown animation
                pg.image.save(self.assets.screen, "screenshot.jpg")
                screenshot = pg.image.load("screenshot.jpg")
     
                running = True
                delay_time = 2000  # ms: 2-second countdown before Pizza_chief starts moving
                countdown_text = self.assets.fonts["regular"].render("", True, self.assets.colors["white"])
                last_time = pg.time.get_ticks()
                start_time = pg.time.get_ticks()
     
                # --------------------------------------------------
                # 2b. Within-trial loop: countdown + movement
                # --------------------------------------------------
                while running:
                    now = pg.time.get_ticks()
                    dt = (now - last_time) / 1000
                    last_time = now
     
                    # Handle abort
                    for event in pg.event.get():
                        if event.type == pg.QUIT or (
                            event.type == pg.KEYDOWN and event.key == pg.K_ESCAPE):
                            running = False
                            trial_running = False
                            threading_running = False  # stop grip-force collection
                            self.save()
                            pg.quit()
                            sys.exit()
     
                    # After the countdown, move Pizza_chief and check collisions
                    if pg.time.get_ticks() - start_time >= delay_time:
                        Pizza_chief.update(dt)
                        Pizza_chief_rects = Pizza_chief.get_rects()
                        (collision, middle_wall_bottom_rect, left_wall_rect, right_wall_rect, collision_side,
                        ) = self.collisions(Pizza_chief_rects, left_position, right_position)
     
                        # -------------------------
                        # Trial failed
                        # -------------------------
                        if collision == "fail":
                            trial_running = False
                            self.assets.screen.blit(self.assets.images["bg"], (0, 0))
                            self.fail()
                            if num_block > 1:
                                self.dict_outcome[wall][adjusted_position].append(0)
                            # End this trial, continue with next one
                            End = datetime.now().strftime("%d/%m/%Y %H:%M:%S.%f")
                            self.store_information(Sub_ID = "" , Type = "Task", Block = num_block, Trial_Num = trial_num, Trial_Outcome = 0,
                                                  Start = Start, End = End, Fail_Location = collision_side, Max_Grip = "", L_Wall_Pos = left_position, R_Wall_Pos = right_position)
                            break
     
                        # -------------------------
                        # Trial successful
                        # -------------------------
                        if collision == "success":
                            trial_running = False
                            self.assets.screen.blit(self.assets.images["bg"], (0, 0))
                            self.celebration()
                            if num_block > 1:
                                self.dict_outcome[wall][adjusted_position].append(1)
                            End = datetime.now().strftime("%d/%m/%Y %H:%M:%S.%f")
                            self.store_information(Sub_ID = "" , Type = "Task", Block = num_block, Trial_Num = trial_num, Trial_Outcome = 1,
                                                   Start = Start, End = End, Fail_Location = collision_side, Max_Grip = "", L_Wall_Pos = left_position, R_Wall_Pos = right_position)
                            # End this trial, continue with next one
                            break
     
                    # ---------------------------------------------
                    # During countdown: show remaining start time
                    # ---------------------------------------------
                    else:
                        remaining = (delay_time - (pg.time.get_ticks() - start_time)) / 1000
                        countdown_text = self.assets.fonts["regular"].render(f"Start in {round(remaining, 1)}", True, self.assets.colors["red"] , )
     
                    # Draw current frame (either countdown or running)
                    self.assets.screen.blit(screenshot, (0, 0))
                    Pizza_chief.draw(self.assets.screen)
                    self.assets.screen.blit(countdown_text, (50, 50))
                    self.assets.screen.blit(self.assets.images["pizza"], (self.assets.screen_width * 0.9, self.assets.screen_height * 0.7) , )
                    pg.display.update()
                    self.clock.tick(60)
        
           # else:
           #     trial = False
           #     running = False
           #     break    
        print(f"Block {num_block} complete!")
            
    def collisions(self, Pizza_chief_rects, left_wall_pos, right_wall_pos):
        """
        Check whether Pizza_chief collides with any static object or the pizza.
    
        Parameters
        ----------
        Pizza_chief_rects : tuple(pg.Rect, pg.Rect, pg.Rect)
            Bounding rectangles for the top, middle and bottom parts of Pizza_chief.
        left_wall_pos : float
            Normalised horizontal position factor for the left wall. Used to compute
            the actual screen-space position.
        right_wall_pos : float
            Normalised horizontal position factor for the right wall.

        Returns
        -------
        collision_detected : {"fail", "success", None}
            Outcome of the collision check. "fail" if Mario hits a wall,
            "success" if he reaches the pizza, None otherwise.
        middle_wall_bottom_rect : pg.Rect
            Rectangle of the middle (brick) wall used for collision checking.
        left_wall_rect : pg.Rect
            Rectangle of the left wall used for collision checking.
        right_wall_rect : pg.Rect
            Rectangle of the right wall used for collision checking.
        collision_side : str or None
            String describing where the collision occurred
            (e.g. "left_wall", "right_wall", "top_wall", "bottom_wall", "pizza"), or None.
        """
        # Unpack Mario's three body-part rectangles
        Pizza_chief_top_rect, Pizza_chief_middle_rect, Pizza_chief_bottom_rect = Pizza_chief_rects
    
        # --- Static environment rectangles ---
    
        top_wall_rect = pg.Rect(
            self.assets.screen_width * 0.2,
            self.assets.screen_height * 0.0,
            self.assets.images["t_wall"].get_width(),
            self.assets.images["t_wall"].get_height(), )
    
        middle_wall_bottom_rect = pg.Rect(
            self.assets.screen_width * 0.5,
            self.assets.bottom_line - self.assets.middle_wall_height,
            self.assets.images["brick_wall"].get_width(),
            self.assets.images["brick_wall"].get_height(), )
    
        start_wall_rect = pg.Rect(
            0,
            0,
            self.assets.screen_width * 0.08,
            self.assets.screen_height * 0.6, )
    
        left_wall_rect = pg.Rect(
            -self.assets.screen_width * left_wall_pos,
            self.assets.screen_height * 0.5,
            self.assets.images["l_wall"].get_width(),
            self.assets.images["l_wall"].get_height(), )
    
        right_wall_rect = pg.Rect(
            self.assets.screen_width * right_wall_pos,
            -self.assets.screen_height * 0.1,
            self.assets.images["r_wall"].get_width(),
            self.assets.images["r_wall"].get_height(), )
    
        pizza_rect = pg.Rect(
            self.assets.screen_width * 0.9,
            self.assets.screen_height * 0.7,
            self.assets.images["pizza"].get_width(),
            self.assets.images["pizza"].get_height(), )
    
        left_side_rect = pg.Rect(middle_wall_bottom_rect.left, 
                                middle_wall_bottom_rect.top, 
                                1,  # 1 pixel wide
                                middle_wall_bottom_rect.height)  # full height
    
        collision_detected = None
        collision_side = None
        
        if (Pizza_chief_bottom_rect.colliderect(middle_wall_bottom_rect)
            or Pizza_chief_middle_rect.colliderect(middle_wall_bottom_rect)):
            # Create a rectangle representing the left side of the wall

            if (Pizza_chief_bottom_rect.colliderect(left_side_rect) or
                Pizza_chief_middle_rect.colliderect(left_side_rect)):
                collision_side = "middle_wall_up" 
                collision_detected = "fail"
            else:
                collision_side = "middle_wall_down"
                collision_detected = "fail"

        if (Pizza_chief_top_rect.colliderect(right_wall_rect)
            or Pizza_chief_middle_rect.colliderect(right_wall_rect)
            or Pizza_chief_bottom_rect.colliderect(right_wall_rect)):
            collision_side = "right_wall"
            collision_detected = "fail"
            
        elif (Pizza_chief_top_rect.colliderect(left_wall_rect)
            or Pizza_chief_middle_rect.colliderect(left_wall_rect)
            or Pizza_chief_bottom_rect.colliderect(left_wall_rect)
            or Pizza_chief_top_rect.colliderect(start_wall_rect)
            or Pizza_chief_middle_rect.colliderect(start_wall_rect)
            or Pizza_chief_bottom_rect.colliderect(start_wall_rect)):
            collision_side = "left_wall"
            collision_detected = "fail"

        elif (Pizza_chief_top_rect.colliderect(top_wall_rect)
            or Pizza_chief_middle_rect.colliderect(top_wall_rect)
            or Pizza_chief_bottom_rect.colliderect(top_wall_rect)):
            collision_side = "top_wall"
            collision_detected = "fail"

        elif (Pizza_chief_top_rect.colliderect(pizza_rect)
            or Pizza_chief_middle_rect.colliderect(pizza_rect)
            or Pizza_chief_bottom_rect.colliderect(pizza_rect)):
            collision_detected = "success"
            
        return collision_detected, middle_wall_bottom_rect, left_wall_rect, right_wall_rect, collision_side

    def celebration(self):
        """
        Show a short reward screen after Pizza_chief successfully collected the pizza.
    
        Increments the global reward counter, displays a large pizza icon and the
        updated counter for ~2 seconds, and allows the experimenter to abort with ESC.
        """
        global threading_running, trial_running, total_reward, num_block
    
        # Update and render total reward counter
        total_reward += 1
        new_reward = self.assets.fonts["huge"].render(f"x {total_reward}", True, self.assets.colors["red"])
        resized_pizza_counter = pg.transform.scale(self.assets.images["pizza"], (self.assets.images["pizza"].get_width() * 2, self.assets.images["pizza"].get_height() * 2))
        
        # Background and static texts
        self.assets.screen.blit(self.assets.texts["success"], (self.assets.screen_width/2 - self.assets.texts["success"].get_width()/2, self.assets.screen_height/3 - self.assets.images["pizza"].get_height()*2))
        self.assets.screen.blit(self.assets.texts["pizza_counter_neu"], (self.assets.screen_width * 0.25 , self.assets.screen_height * 0.40))
        self.assets.screen.blit(resized_pizza_counter, (self.assets.screen_width * 0.43 , self.assets.screen_height * 0.35))
        self.assets.screen.blit(new_reward, (self.assets.screen_width * 0.55 , self.assets.screen_height * 0.35))
        
        running = True
        counter = -2
        last_time = pg.time.get_ticks()
        while running:
            now = pg.time.get_ticks()
            dt = (now - last_time) / 1000
            last_time = now
            counter += dt
            
            # Stop reward animation after ~2 seconds
            if counter > 0:
                running = False
                
            # Handle abort
            for event in pg.event.get():
                if event.type == pg.QUIT or (event.type == pg.KEYDOWN and event.key == pg.K_ESCAPE):
                    running = False
                    trial_running = False
                    threading_running = False
                    self.save()
                    pg.quit()
                    sys.exit()
                   
            pg.display.flip()
            self.clock.tick(60)
            
    def fail(self):
        """
        Show a short failure screen when Pizza_chief hits an obstacle.
    
        Displays the unconscious Pizza_chief sprite for ~2.5 seconds.
        ESC aborts the experiment.
        """
        global threading_running, trial_running
    
        # Draw failure screen
        self.assets.screen.blit(self.assets.images["Pizza_chief_unconscious"], (0, 0))
        pg.display.update()
    
        running = True
        counter = -2.5
        last_time = pg.time.get_ticks()
    
        while running:
            now = pg.time.get_ticks()
            dt = (now - last_time) / 1000
            last_time = now
            counter += dt
    
            if counter > 0:
                running = False
    
            # Handle abort
            for event in pg.event.get():
                if event.type == pg.QUIT or (
                    event.type == pg.KEYDOWN and event.key == pg.K_ESCAPE):
                    running = False
                    trial_running = False
                    threading_running = False
                    self.save()
                    pg.quit()
                    sys.exit()
    
            pg.display.flip()
            self.clock.tick(60)

        
    def brake(self):
        """
        Display a short break screen between repetitions.
    
        Shows explanatory text and waits until the experimenter presses SPACE
        to continue, or ESC to abort the experiment.
        """
        global threading_running, trial_running

        # Show the brake text
        self.assets.screen.fill(self.assets.colors["white"])
        self.assets.screen.blit(self.assets.images["ukk_logo"], (self.assets.screen_width * 0.5 - self.assets.images["ukk_logo"].get_width() / 2, 0))
        self.assets.screen.blit(self.assets.texts["brake_text_1"], (self.assets.screen_width * 0.5 - self.assets.texts["brake_text_1"].get_width() / 2, self.assets.screen_height * 0.3))
        self.assets.screen.blit(self.assets.texts["brake_text_2"], (self.assets.screen_width * 0.5 - self.assets.texts["brake_text_2"].get_width() / 2, self.assets.screen_height * 0.5))
        running = True
        while running:   
            # Handle abort
            for event in pg.event.get():
                if event.type == pg.QUIT or (event.type == pg.KEYDOWN and event.key == pg.K_ESCAPE):
                    running = False
                    trial_running = False
                    threading_running = False
                    self.save()
                    pg.quit()
                    sys.exit()
                
                # If the event is the space bar then the task continues
                if event.type == pg.KEYDOWN and event.key == pg.K_SPACE:
                    running = False

            pg.display.flip()
            self.clock.tick(60)

    
    def create_folder(self, directory):
        """Creates folders for storing results."""
        if not os.path.exists(directory):
            os.makedirs(directory)
            # Use os.path.join to handle slashes automatically
            path = os.path.join(directory, "Force_Profiles")
            os.makedirs(path, exist_ok=True)

    def save(self):
        """
        Saves stored information into dataframes
        """
        print("in save")
        # DataFrames bauen
        final_settings_df = pd.DataFrame(self.dict_outcome["final_settings"], index=[0])
        results_df = pd.DataFrame(self.dict_results)
    
        # Zielordner pro Proband*in
        subj_dir = os.path.join("Results", self.subject_id)
        self.create_folder(subj_dir)
    
        final_settings_df.to_csv(os.path.join(subj_dir, "final_settings.csv"), index=False)
        results_df.to_csv(os.path.join(subj_dir, "results.csv"), index=False)

    def run(self):
        global wall, num_block, trial_num
        
        """
        Run the full experiment for a single participant.
        
        Sequence:
        1) Introduction and subject ID input.
        2) Max grip force calibration.
        3) Task blocks with wall personalisation.
        """
        
        self.introduction()
        self.max_grip = self.max_force_test()
        for block in BLOCK_PLAN:
            wall = block
            self.task()
            num_block += 1 
            trial_num = -10
            self.save()
            if block == "left_wall":
                self.brake()
    

if __name__ == "__main__":
    
    # Start background thread reading grip-force data
    sampler_thread = threading.Thread(target=grip_device_reader)
    sampler_thread.start()
    
    # Run the game
    game = Game()
    df = game.run()
    
    #Stop the grip force process when the game ends
    trial_running = False
    threading_running = False
    
    print("Game Over. Grip process stopped.")
    
    pg.quit()
    sys.exit()