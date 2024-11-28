import nbtlib
import os
import tkinter as tk
import numpy as np
from queue import Queue
from tkinter.ttk import *
from tkinter.filedialog import askopenfilename
from pathlib import Path
from threading import Thread

class FixerApp:
    def __init__(self, window: tk.Tk):
        self.window = window
        self.level = tk.StringVar(master=window, value="No Level Selected")
        self.world = None
        self.btn_convert = None
        self.btn_select = None
        self.lbl_select = None
        self.lbl_progress = None
        self.progress = None
        self.progress_state = tk.StringVar(master=window, value="Finding chunks...")
        self.chunk_progress = 0
        self.dats = []
        self.queue = Queue()
        self.thread = None
    
    def select_path(self):
        filepath = askopenfilename(
            filetypes=[("Data Files", "*.dat")]
        )
        if not filepath:
            return
        else:
            self.level.set(filepath)
            self.world = Path(filepath).parent.absolute()
            self.btn_convert['state'] = "normal"

    def run_alter_world(self):
        self.lbl_progress.grid(row=2, column=1)
        self.progress.grid(row=3, column=0, columnspan=3, sticky = tk.W+tk.E)
        self.btn_convert['state'] = "disabled"
        self.btn_select['state'] = "disabled"

        self.thread = ConvertWorldThread(self, self.world, self.queue)
        self.thread.start()
        self.check_queue()

    def check_queue(self):
        dead = False
        while not self.queue.empty():
            item = self.queue.get()
            if item[0] == "progress":
                self.progress['value'] += item[1]
            elif item[0] == "status":
                self.progress_state.set(item[1])
            else:
                self.progress.grid_forget()
                self.progress_state.set("Complete!")
                dead = True

        if not dead:  
            self.window.after(10, self.check_queue)

    def setup(self):
        self.window.title("Alpha Tree Fixer")
        self.lbl_select = tk.Label(master=self.window, textvariable=self.level)
        self.btn_select = tk.Button(
            master=self.window,
            text="Select World level.dat",
            command=self.select_path
        )
        self.btn_convert = tk.Button(
            master=self.window,
            text="Convert World Leaves",
            command=self.run_alter_world,
            state="disabled"
        )
        self.progress = Progressbar(master=self.window, orient="horizontal", length=200, mode='determinate')
        self.lbl_progress = tk.Label(master=self.window, textvariable=self.progress_state)

        self.btn_convert.grid(row=1, column=1, pady=10, padx=10)
        self.btn_select.grid(row=0, column=2, padx=10, pady=10)
        self.lbl_select.grid(row=0, column=0, columnspan=2, sticky=tk.W+tk.E)

        self.window.mainloop()

class ConvertWorldThread(Thread):
    def __init__(self, app: FixerApp, world: str, queue: Queue):
        super(ConvertWorldThread, self).__init__()
        self.app = app
        self.dats = []
        self.world = world
        self.queue = queue

    def run(self):
        self.alter_world_leaves()
        self.queue.put(("kill", "success"))
    
    #region alter_world
    def find_dats(self, path: str, top = False):
        '''
        Recursively find all .dat files in a world folder
        Ignores level.dat, level.dat_old, session.lock 

        Args:
            top: True if call is top of recursive stack, used for progress bar logic
        '''
        files = os.listdir(path)
        for file in files:
            if os.path.isdir(os.path.join(path, file)):
                self.find_dats(os.path.join(path, file))
            elif file != "level.dat" and file != "level.dat_old" and file != "session.lock":
                self.dats.append(os.path.join(path, file))

            if top:
                self.queue.put(("progress", 10 / (len(files) - 3)))
                
    def alter_world_leaves(self):
        '''
        Take a world path and a target value. Finds all .dats, creates a block_map of leaf locations, and alters their data to a target value.
        
        Args:
            world_path: file path to the world
            target_value: the value to set leaf block data to
        '''
        self.find_dats(self.world, True)
        leaf_map = self.compile_chunk_blocks(18)
        self.write_from_block_map(leaf_map, 0)

    def find_blocks(self, chunk_path: str, block_id: int):
        '''
        Find the byte array indices of blocks in target file

        Args:
            chunk_path: The path for the target .dat file
            block_id: The id of the block to search for

        Returns:
            A list of block indices
        '''
        chunk = nbtlib.load(chunk_path)
        blocks = np.array(chunk.find("Blocks"), dtype=np.uint8)
        block_id = np.uint8(block_id)

        indices = np.where(blocks == block_id)[0]
        return indices.tolist()

    def compile_chunk_blocks(self, block_id: int):
        '''
        Find the location of all blocks every chunk in a file
        Uses current dats attribute for chunklist

        Args:
            block_id: The id of the block to search for (usually 18 for leaves)
        
        Returns:
            A dict of .dat paths as keys with lists of block indices as their values
        '''
        self.queue.put(("status", 'Finding all leaves...'))
        block_map = dict()
        for chunk_path in self.dats:
            block_map[chunk_path] = self.find_blocks(chunk_path, block_id)
            self.queue.put(("progress", 25 / (len(self.dats) - 3)))

        return block_map

    def write_from_block_map(self, block_map: dict, target_value):
        '''
        Take a block_map and alter the data of all leaves in the data tag

        Args:
            block_map: Dictionary mapping chunk path to list of block indices
            target_value: the value to set block data to
        '''
        self.queue.put(("status", "Editing leaf blockdata..."))
        for chunk_path in block_map:
            if len(block_map[chunk_path]) != 0:
                chunk = nbtlib.load(chunk_path)
                data = chunk.find("Data")
                new_data = np.array(data, dtype=np.int8)

                for leaf in block_map[chunk_path]:
                    byte_index = leaf // 2
                    is_low = leaf % 2 == 0

                    # Extract the current byte as unsigned for bitwise
                    byte = np.uint8(new_data[byte_index])

                    if is_low:
                        new_byte = (byte & 0xF0) | (target_value & 0x0F)
                    else:
                        new_byte = (byte & 0x0F) | ((target_value & 0x0F) << 4)

                    # Two's complement conversion for signed bytes
                    if new_byte > 127:
                        new_byte = int(new_byte) - 256

                    new_data[byte_index] = new_byte
                signed_array = new_data.astype(np.int8)
                byte_array = [nbtlib.Byte(value) for value in signed_array]
                chunk['']['Level']['Data'] = nbtlib.ByteArray(byte_array)
                chunk.save()
            self.queue.put(("progress", 65 / (len(block_map) - 3)))
    #endregion 

def main():
    window = tk.Tk()
    gui = FixerApp(window)
    gui.setup()


if __name__ == "__main__":
    main()
    