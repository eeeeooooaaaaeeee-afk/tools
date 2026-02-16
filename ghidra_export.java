//@category Export

import java.io.*;
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;

public class AAA_export extends GhidraScript {// change 'class (your name) extends' to file name
    @Override
    protected void run() throws Exception {
        File out = askFile("Save decompilation to", "Save");
        if (out == null) return;

        DecompInterface ifc = new DecompInterface();
        ifc.openProgram(currentProgram);

        FunctionManager fm = currentProgram.getFunctionManager();
        FunctionIterator it = fm.getFunctions(true);

        int count = 0;
        try (BufferedWriter bw = new BufferedWriter(new FileWriter(out))) {
            while (it.hasNext() && !monitor.isCancelled()) {
                Function fn = it.next();
                count++;

                DecompileResults res = ifc.decompileFunction(fn, 60, monitor);
                String code = "/* decompile failed */";
                if (res != null && res.getDecompiledFunction() != null) {
                    code = res.getDecompiledFunction().getC();
                }

                bw.write("\n\n================================================================================\n");
                bw.write("Function: " + fn.getName(true) + " @ " + fn.getEntryPoint() + "\n");
                bw.write("================================================================================\n");
                bw.write(code);
                bw.write("\n");

                if (count % 50 == 0) {
                    println("Done: " + count);
                }
            }
        }

        ifc.dispose();
        println("Saved: " + out.getAbsolutePath());
    }
}
