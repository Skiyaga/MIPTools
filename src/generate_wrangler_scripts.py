import os
from itertools import zip_longest
import pandas as pd
import numpy as np
import argparse
import sys
import datetime

# Read input arguments
parser = argparse.ArgumentParser(
    description=""" Generate bash scripts to be used for processing
    after a MIP sequencing run.
    """)
parser.add_argument("-e", "--experiment-id",
                    help=("A Unique id given to each sequencing "
                          "run by the user."),
                    required=True)
parser.add_argument("-c", "--cpu-count",
                    type=int,
                    help="Number of available processors to use.",
                    default=1)
parser.add_argument("-n", "--server-num",
                    type=int,
                    help="Starting number for MIP server.",
                    default=1)
parser.add_argument("-d", "--data-dir",
                    help=("Absolute path to the directory where sequencing "
                          " (.fastq/.fastq.gz) files are located."),
                    default="/opt/data")
parser.add_argument("-a", "--analysis-dir",
                    help=("Absolute path to base directory for "
                          "MIPWrangler working directory."),
                    default="/opt/analysis")
parser.add_argument("-w", "--cluster-script",
                    help=("MIPWrangler script name. Absolute path"
                          "if not in $PATH."),
                    default="runMIPWranglerCurrent.sh")
parser.add_argument("-r", "--project-resource-dir",
                    help=("Path to directory where project specific resources "
                          "such as probe sets used, mip arm info etc. are"),
                    default="/opt/project_resources")
parser.add_argument("-b", "--base-resource-dir",
                    help=("Path to directory where general resources such as "
                          "barcode dictionary, sample sheet "
                          "templates etc. are."),
                    default="/opt/resources")
parser.add_argument("-l", "--sample-list",
                    help=("File providing a list of samples with associated "
                          "information."),
                    required=True)
parser.add_argument("-s", "--sample-set",
                    help=("Sample set to be processed."),
                    required=True)
parser.add_argument("-p", "--probe-set",
                    help=("Probe set to be processed."),
                    required=True)
parser.add_argument("-k", "--keep-files",
                    help=("Keep intermediate files generated by MIPWrangler."),
                    action="store_true")
parser.add_argument("-x", "--stitch-options",
                    help=("Probe set to be processed."),
                    required=True)
# parse arguments from command line
args = vars(parser.parse_args())
experiment_id = args["experiment_id"]
cluster_script = args["cluster_script"]
cpu_count = args["cpu_count"]
server_num = args["server_num"]
fastq_dir = os.path.abspath(args["data_dir"])
analysis_dir = os.path.abspath(args["analysis_dir"])
project_resource_dir = os.path.abspath(args["project_resource_dir"])
base_resource_dir = os.path.abspath(args["base_resource_dir"])
sample_list_file = os.path.join(analysis_dir, args["sample_list"])
raw_mip_ids_dir = os.path.join(analysis_dir, "mip_ids")
sam_set = args["sample_set"]
pr_set = args["probe_set"]
keep_files = args["keep_files"]
stitch_options = args["stitch_options"]
if stitch_options == "none":
    stitch_options = []
else:
    stitch_options = stitch_options.split(",")
# create dirs if they do not exist
if not os.path.exists(raw_mip_ids_dir):
    os.makedirs(raw_mip_ids_dir)
# First part of the MIPWrangler process is to extract the sequences and
# stitch forward and reverse reads. This is done with mipSetupAndExtractByArm
# read in sample information
sample_info = {}
with open(sample_list_file) as infile:
    linenum = 0
    for line in infile:
        newline = line.strip().split("\t")
        if linenum == 0:
            colnames = newline
            linenum += 1
        else:
            sample_dict = {colname: colvalue for colname, colvalue
                           in zip(colnames, newline)}
            sample_set = sample_dict["sample_set"]
            sample_name = sample_dict["sample_name"]
            probe_sets = sample_dict["probe_set"].split(";")
            if (sample_set == sam_set) and (pr_set in probe_sets):
                replicate_number = sample_dict["replicate"]
                sample_id = "-".join([sample_name,
                                      sample_set,
                                      replicate_number])
                if sample_id in sample_info:
                    print("Repeating sample name ", sample_id)
                if not sample_id.replace("-", "").isalnum():
                    print(("Sample IDs can only contain "
                           "alphanumeric characters and '-'. "
                           "{} has invalid characters.").format(sample_id))
                    continue
                sample_dict["sample_index"] = linenum
                linenum += 1
                sample_info[sample_id] = sample_dict
mipset_table = os.path.join(project_resource_dir, "mip_ids", "mipsets.csv")
mipsets = pd.read_csv(mipset_table)
mipset_list = mipsets.to_dict(orient="list")
# convert the mip sets dataframe to dict for easy access
all_probes = {}
# keep mip arm files for each mip set in a dictionary
mip_arms_dict = {}
for mipset in mipset_list:
    list_m = mipset_list[mipset]
    # the file name should be the second line in the mipsets.csv
    mip_arms_dict[mipset] = list_m[0]
    # rest of the lines have probe names in the set
    set_m = set(list_m[1:])
    set_m.discard(np.nan)
    all_probes[mipset] = set_m
subset_names = []
# For the sample and probe set create
# 1) MIPWrangler input files (samples etc.)
# 2) Scripts for MIPWrangler Part I (extract + stitch)
# 3) Scripts for MIPWrangler Part II (clustering)
probes = set()
mip_arms_list = []
pset_names = pr_set.split(",")
for p_name in pset_names:
    try:
        temp_probes = all_probes[p_name]
    except KeyError:
        print(("Probe set name {} is not present in the mipsets "
               "file. This probe set will be ignored.").format(p_name))
        continue
    arm_file = os.path.join(project_resource_dir,
                            "mip_ids",
                            mip_arms_dict[p_name])
    try:
        with open(arm_file) as infile:
            mip_arms_list.append(pd.read_table(infile))
            probes.update(temp_probes)
    except IOError:
        print(("MIP arm file {} is required but missing for "
              "the probe set {}. Probe set will be ignored.").format(
                  arm_file, p_name))
if len(mip_arms_list) == 0:
    print(("No MIP arms file were found for the probe sets {}"
           " scripts will not be generated for them. Make sure "
           "relevant files are present in the {} directory").format(
           pset_names, project_resource_dir))
    sys.exit(1)
mip_arms_table = pd.concat(mip_arms_list,
                           ignore_index=True).drop_duplicates()
mip_arms_table = mip_arms_table.loc[
    mip_arms_table["mip_family"].isin(probes)
]
mip_family_names = probes
# Create MIPWrangler Input files
subset_name = sam_set + "_" + "_".join(pset_names)
sample_subset = list(sample_info.keys())
with open(
    os.path.join(
        raw_mip_ids_dir,
        subset_name + "_allMipsSamplesNames.tab.txt"
    ), "w"
) as outfile:
    outfile_list = ["\t".join(["mips", "samples"])]
    mips_samples = zip_longest(
        mip_family_names, sample_subset, fillvalue=""
    )
    for ms in mips_samples:
        outfile_list.append("\t".join(ms))
    outfile.write("\n".join(outfile_list))
    pd.DataFrame(mip_arms_table).groupby(
        "mip_id").first().reset_index().dropna(
            how="all", axis=1
            ).to_csv(
                os.path.join(
                    raw_mip_ids_dir,
                    subset_name + "_mipArms.txt"
                ), sep="\t",
                index=False
            )
# Create MIPWrangler part I script commands
stitch_commands = [
    ["cd", analysis_dir],
    ["nohup MIPWrangler mipSetupAndExtractByArm", "--mipArmsFilename",
     os.path.join(raw_mip_ids_dir, subset_name + "_mipArms.txt"),
     "--mipSampleFile", os.path.join(
            raw_mip_ids_dir,
            subset_name + "_allMipsSamplesNames.tab.txt"
     ), "--numThreads", str(cpu_count), "--masterDir analysis",
     "--dir", fastq_dir, "--mipServerNumber", str(server_num)]
]
stitch_commands[-1].extend(stitch_options)
if keep_files:
    stitch_commands[-1].append("--keepIntermediateFiles")
# Create MIPWrangler part II script commands
now = datetime.datetime.now()
run_date = now.strftime("%Y%m%d")
info_file = os.path.join(analysis_dir,
                         "analysis/populationClustering/allInfo.tab.txt")
renamed_info = os.path.join(analysis_dir, experiment_id + "_"
                            + subset_name + "_" + run_date + ".txt")
wrangler_commands = [
    ["cd", "analysis"],
    ["nohup", cluster_script, str(server_num), str(cpu_count)],
    ["mv", os.path.join(analysis_dir, "analysis/logs"), analysis_dir],
    ["mv", os.path.join(analysis_dir, "analysis/scripts"), analysis_dir],
    ["mv", os.path.join(analysis_dir, "analysis/resources"), analysis_dir],
    ["mv", os.path.join(analysis_dir, "analysis/nohup.out"),
     os.path.join(analysis_dir, "nohup2.out")],
    ["mv", info_file, renamed_info],
    ["pigz", "-9", "-p", str(cpu_count), renamed_info]
]
extraction_summary_file = "extractInfoSummary.txt"
extraction_per_target_file = "extractInfoByTarget.txt"
stitching_per_target_file = "stitchInfoByTarget.txt"
for filename in [extraction_summary_file,
                 extraction_per_target_file,
                 stitching_per_target_file]:
    stat_command = ["find", os.path.join(analysis_dir, "analysis"),
                    "-name", filename, "-exec", "cat",
                    "{}", "+", ">", os.path.join(analysis_dir, filename)]
    wrangler_commands.append(stat_command)
for filename in [extraction_summary_file,
                 extraction_per_target_file,
                 stitching_per_target_file]:
    zip_command = ["pigz", "-9", "-p", str(cpu_count), filename]
    wrangler_commands.append(zip_command)
server_num += 1
if subset_name in subset_names:
    print("%s is already in subset_names!" % subset_name)
subset_names.append(subset_name)

# Save all scripts to files.
with open(os.path.join(analysis_dir, subset_name + ".sh"), "w") as outfile:
    outfile.write("\n".join(
        [" ".join(c) for c in stitch_commands]) + "\n")
    outfile.write("\n".join(
        [" ".join(c) for c in wrangler_commands]) + "\n")
