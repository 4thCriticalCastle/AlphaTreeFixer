import nbtlib
import os
import tkinter as tk
import time
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
                self.queue.put(("progress", 20 / (len(files) - 3)))
                
    def alter_world_leaves(self):
        '''
        Take a world path and a target value. Finds all .dats, creates a block_map of leaf locations, and alters their data to a target value.
        
        Args:
            world_path: file path to the world
            target_value: the value to set leaf block data to
        '''
        self.find_dats(self.world, True)
        leaf_map = self.compile_chunk_blocks(18)
        self.write_from_block_map(leaf_map, 18)

    def find_blocks(self, chunk_path: str, block_id: int):
        '''
        Find the byte array indices of blocks in target file

        Args:
            path: The path for the target .dat file
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

        Args:
            pathlist: The list of paths for all chunk .dat files to search
            block_id: The id of the block to search for 
        
        Returns:
            A dict of .dat paths as keys with lists of leaf indices as their values
        '''
        self.queue.put(("status", 'Finding all leaves...'))
        block_map = dict()
        for chunk_path in self.dats:
            block_map[chunk_path] = self.find_blocks(chunk_path, block_id)
            self.queue.put(("progress", 60 / (len(self.dats) - 3)))

        return block_map

    def write_from_block_map(self, block_map: dict, target_value):
        '''
        Take a block_map and alter the data of all leaves in the data array

        Args:
            block_map: Dictionary mapping chunk path to list of leaf indices
            target_value: the value to set leaf block data to
        '''
        self.queue.put(("status", "Editing leaf blockdata..."))
        for chunk_path in block_map:
            chunk = nbtlib.load(chunk_path)
            data = chunk.find("Data")
            new_data = np.array(data.unpack())
            for leaf in block_map[chunk_path]:
                byte_index = leaf // 2
                is_low = leaf % 2 == 0

                byte = data[byte_index].unpack()

                if is_low:
                    new_byte = (byte & 0xF0) | (target_value & 0x0F)
                else:
                    new_byte = (byte & 0x0F) | (target_value & 0x0F) << 4

                if (new_byte > 127):
                    new_byte = new_byte - 256

                new_data[byte_index] = new_byte
            chunk['']['Level']['Data'] = nbtlib.ByteArray(new_data)    
            chunk.save()
            self.queue.put(("progress", 20 / (len(block_map) - 3)))
    #endregion 

#region alter_world benchmarking
class ConvertWorldBenchmarking:
    def __init__(self, world: str):
        self.dats = []
        self.world = world

    def find_dats(self, path: str):
        '''
        Recursively find all .dat files in a world folder
        Ignores level.dat, level.dat_old, session.lock 
        '''
        files = os.listdir(path)
        for file in files:
            if os.path.isdir(os.path.join(path, file)):
                self.find_dats(os.path.join(path, file))
            elif file != "level.dat" and file != "level.dat_old" and file != "session.lock":
                self.dats.append(os.path.join(path, file))

    def alter_world_leaves(self):
        '''
        Take a world path and a target value. Finds all .dats, creates a block_map of leaf locations, and alters their data to a target value.
        
        Args:
            world_path: file path to the world
            target_value: the value to set leaf block data to
        '''
        self.find_dats(self.world)
        leaf_map = self.compile_chunk_blocks(18)
        self.write_from_block_map(leaf_map, 18)



    def find_blocks(self, chunk_path: str, block_id: int):
        '''
        Find the byte array indices of blocks in target file

        Args:
            path: The path for the target .dat file
            block_id: The id of the block to search for

        Returns:
            A list of block indices
        '''
        chunk = nbtlib.load(chunk_path)
        blocks = np.array(chunk.find("Blocks"), dtype=np.uint8)
        block_id = np.uint8(block_id)

        indices = np.where(blocks == block_id)[0]
        return indices.tolist()

    def compile_chunk_blocks_revised(self, block_id: int):
        '''
        Find the location of all blocks every chunk in a file

        Args:
            pathlist: The list of paths for all chunk .dat files to search
            block_id: The id of the block to search for 
        
        Returns:
            A dict of .dat paths as keys with lists of leaf indices as their values
        '''
        block_map = dict()
        for chunk_path in self.dats:
            block_map[chunk_path] = self.find_blocks_revised(chunk_path, block_id)

        return block_map        

    def find_blocks(self, chunk_path: str, block_id: int):
        '''
        Find the byte array indices of blocks in target file

        Args:
            path: The path for the target .dat file
            block_id: The id of the block to search for

        Returns:
            A list of block indices
        '''
        chunk = nbtlib.load(chunk_path)
        blocks = np.array(chunk.find("Blocks").unpack(), dtype=np.uint8)
        block_id = np.uint8(block_id)

        indices = np.where(blocks == block_id)[0]
        return indices.tolist()

    def compile_chunk_blocks(self, block_id: int):
        '''
        Find the location of all blocks every chunk in a file

        Args:
            pathlist: The list of paths for all chunk .dat files to search
            block_id: The id of the block to search for 
        
        Returns:
            A dict of .dat paths as keys with lists of leaf indices as their values
        '''
        block_map = dict()
        for chunk_path in self.dats:
            block_map[chunk_path] = self.find_blocks(chunk_path, block_id)

        return block_map
    
    def unpack_data(self, chunk_path: str):
        '''
        Convert the data bytearray to a list of nibbles that correctly map to the blockid list

        Args:
            path: Path to the chunk .dat file
            
        Returns:
            A 32768 long list of ints representing the signed data nibbles of each block
        '''
        world = nbtlib.load(chunk_path)
        data = world.find("Data")
        nibbles = []
        for byte in data:
            raw = byte.unpack()
            low = raw & 0x0F
            high = (raw >> 4) & 0x0F
            nibbles.append(low)
            nibbles.append(high)

        return nibbles

    def repack_data(self, chunk_path: str, data: list):
        '''
        Convert a list of nibbles back to a bytearray and save them to the data object
        '''
        new_data = []
        for i in range(0, len(data), 2):
            # Bitwise ops to combine nibbles
            new_byte = (data[i+1] << 4) | data[i]
            # Two's complement conversion (nbtlib expects signed)
            if (new_byte > 127):
                new_byte = new_byte - 256
            new_data.append(nbtlib.Byte(new_byte))

        new_data = nbtlib.ByteArray(new_data)
        chunk = nbtlib.load(chunk_path)
        chunk['']['Level']['Data'] = new_data 
        chunk.save()   

    def write_from_block_map(self, block_map: dict, target_value):
        '''
        Take a block_map and alter the data of all leaves in the data array

        Args:
            block_map: Dictionary mapping chunk path to list of leaf indices
            target_value: the value to set leaf block data to
        '''
        for chunk in block_map:
            data = self.unpack_data(chunk)
            old_data = data[:]
            for leaf in block_map[chunk]:
                data[leaf] = target_value
            if old_data != data:
                self.repack_data(chunk, data)

#endregion

def main():
    # window = tk.Tk()
    # gui = FixerApp(window)
    # gui.setup()

    BenchConverter = ConvertWorldBenchmarking("C:\\Users\\ducks\\AppData\\Roaming\\.betacraft\\TreeFixTesting\\saves\\world4")

    BenchConverter.alter_world_leaves()


if __name__ == "__main__":
    main()
    