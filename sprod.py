"""
A convinient function to wrap all necessary processed in Sprod. Minimal data processing is required.
A 'Counts.txt' and a 'Spot_metadata.csv' is required to run this script.
Also, if the input folder contains a image tif file, it will be used as the input matching
image for feature extraction. Both files have rows as spots and with the same order.
For data with matching image, the "Spot_metadata.csv" must have a "Spot_radius" 
column for spot features, or "Row" and "Col" columns for block features.

Dependency
----------
R >= 4.0.2
    Rcpp
    distances
    dplyr

Python dependencies will be handeled automatically by installing the sprod package.

"""

import os
import sys
import argparse
import logging
from multiprocessing import Pool
from sprod.feature_extraction import extract_img_features
from sprod.pseudo_image_gen import make_pseudo_img
from sprod.slide_seq_stiching import stiching_subsampled_patches
from sprod.slideseq_make_patches import subsample_patches
import subprocess


def sprod_worker(cmd):
    """
    A simple wrapper for running denoise jobs.
    --------
    denoise.R options for reference.
    make_option(c("-e", "--Exp"), help="Expression matrix"),
    make_option(c("-c", "--Cspot"), help="Spot metadata, contains X, Y coordinates."),
    make_option(c("-f", "--ImageFeature"), help="Extracted image features"),
    make_option(c("-n", "--numberPC"), help="# Number of PCs to use"),
    make_option(c("-r", "--Rratio"),help="Spot neighborhood radius ratio, 0-1, radius=R*min(xmax-xmin,ymax-ymin)"), 
    make_option(c("-u", "--U"),help="# perplexity, Tunable"),
    make_option(c("-k", "--K"),help="latent space dimension, Tunable"), 
    make_option(c("-l", "--lambda"),help="# regularizer, tunable"),
    make_option(c("-t", "--L_E"),help="regularizer for denoising"), 
    make_option(c("-m", "--margin"), help="Margin for bisection search, smaller = slower => accuracy u"),
    make_option(c("-d","--diagNeighbor"),help = "To prevent over smooth."),
    make_option(c("-s", "--scriptPath"), help="path to the software folder"),
    make_option(c("-o", "--outputPath"), help="Output path"),
    make_option(c("-p", "--projectID"), help="# project name, First part of names in the output"),
    """
    log_fn = cmd[-1]
    cmd = cmd[:-1]
    print(cmd)
    with open(log_fn, "a") as outfile:
        subprocess.run(cmd, stdout=outfile, stderr=outfile)
    # os.system('rm -r output_fn') # Get rid of output.
    return


class StreamToLogger(object):
    """
    Fake file-like stream object that redirects writes to a logger instance.
    """

    def __init__(self, logger, log_level=logging.INFO):
        self.logger = logger
        self.log_level = log_level
        self.linebuf = ""

    def write(self, buf):
        for line in buf.rstrip().splitlines():
            self.logger.log(self.log_level, line.rstrip())

    def flush(self):
        pass

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description="Main function for running sprod.",
    )

    parser.add_argument(
        "input_path", type=str, help="Input folder containing all necessary files."
    )

    parser.add_argument("output_path", type=str, help="Output path")

    parser.add_argument(
        "--input_type",
        "-y",
        default="single",
        type=str,
        help="The input type decides the running mode for sprod, select from {'single','patches'}. \
            For smaller datasets, such as Visium, use 'single' mode. For larger datasets such as \
            Slide-seq, use 'patches' mode",
    )

    parser.add_argument(
        "--output_prefix",
        "-p",
        default="sprod",
        type=str,
        help="Output prefix used in the output.",
    )
    parser.add_argument(
        "--sprod_npc",
        "-sn",
        type=int,
        default=-1,
        help="Number of PCs to use, positive integers. -1 to use all PCs from the features.",
    )
    parser.add_argument(
        "--sprod_umap",
        "-su",
        default=False,
        action="store_true",
        help="Toggle to use UMAP on top of PCA to represent features. ",
    )
    parser.add_argument(
        "--sprod_R",
        "-r",
        default=0.08,
        type=float,
        help="Spot neighborhood radius ratio, 0-1, \
            radius=R*min(xmax-xmin,ymax-ymin).",
    )
    parser.add_argument(
        "--spord_perplexity",
        "-u",
        default=250,
        type=int,
        help="Perplexity, used in Sprod to find the proper Gaussian kernal \
            for distant representation.",
    )
    parser.add_argument(
        "--sprod_margin",
        "-g",
        default=0.001,
        type=float,
        help="Margin for bisection search, used in Sprod to find the proper \
            Gaussian kernal. smaller = slower => accurate u",
    )
    parser.add_argument(
        "--sprod_latent_dim",
        "-k",
        default=10,
        type=int,
        help="Dimension of the latent space used in sprod to represent spots.",
    )
    parser.add_argument(
        "--sprod_graph_reg",
        "-l",
        default=1,
        type=float,
        help="Regularization term for spot graph contructed in sprod.",
    ),
    parser.add_argument(
        "--sprod_weight_reg",
        "-w",
        default=0.625,
        type=float,
        help="Regularization term for the denoising weights.",
    )
    parser.add_argument(
        "--sprod_diag",
        "-d",
        action="store_true",
        default=False,
        help="Toggle to force graph weights to be diagnoal, useful in reducing \
            over smoothing",
    )

    parser.add_argument(
        "--image_feature_type",
        "-i",
        type=str,
        default="spot_intensity",
        help="Type of feature extracted. combination from {'spot', 'block'} and \
            {'intensity', 'texture'} with '_' as delimiter. Only relevant if the \
            input dataset contains an matching tif image.",
    )

    parser.add_argument(
        "--warm_start",
        "-ws",
        default=False,
        action="store_true",
        help="Toggle for warm start, which will skip all preprocessing steps \
            including feature extraction and patch-making.",
    )

    parser.add_argument(
        "--num_of_patches",
        "-pn",
        type=int,
        default=10,
        help="Number of subsampled patches. Only works when --input_type is patches.",
    )

    parser.add_argument(
        "--num_of_batches",
        "-pb",
        type=int,
        default=10,
        help="How many times subsampling is ran. Only works when --input_type is patches.",
    )

    parser.add_argument(
        "-ci",
        "--img_type",
        type=str,
        default="he",
        help="Input image type. {'he', 'if'}. The 'if' mode is only tested on Visium-assocaited data.",
    )

    args = parser.parse_args()
    input_path = args.input_path
    output_path = args.output_path
    input_type = args.input_type
    warm_start = args.warm_start
    output_prefix = args.output_prefix
    sprod_npc = args.sprod_npc
    sprod_umap = args.sprod_umap
    sprod_R = args.sprod_R
    spord_perplexity = args.spord_perplexity
    sprod_margin = args.sprod_margin
    sprod_latent_dim = args.sprod_latent_dim
    sprod_graph_reg = args.sprod_graph_reg
    sprod_weight_reg = args.sprod_weight_reg
    sprod_diag = args.sprod_diag
    image_feature_type = args.image_feature_type
    pn = args.num_of_patches
    pb = args.num_of_batches

    # getting script path for supporting codes.
    sprod_path = os.path.abspath(__file__)
    sprod_path = "/".join(sprod_path.split("/")[:-1]) + '/sprod'
    sprod_script = os.path.join(sprod_path, "denoise.R")

    if not os.path.exists(output_path):
        os.makedirs(output_path)

    # Setting up logs
    log_fn = os.path.join(output_path, "sprod_log.txt")
    if os.path.exists(log_fn):
        os.remove(log_fn)
    logging.basicConfig(
        filename=log_fn,
        format="%(asctime)s,%(levelname)s:::%(message)s",
        datefmt="%H:%M:%S",
        level="INFO",
    )
    # redirects stdout and stderr to logger
    stdout_logger = logging.getLogger("STDOUT")
    sl = StreamToLogger(stdout_logger, logging.INFO)
    sys.stdout = sl
    stderr_logger = logging.getLogger("STDERR")
    sl = StreamToLogger(stderr_logger, logging.ERROR)
    sys.stderr = sl

    # cold start means image features will be extracted first.
    if not warm_start:
        logging.info("Cold start, processing from counts and image data.")
        # check if input path contains necessary data
        if not (
            os.path.exists(os.path.join(input_path, "Counts.txt"))
            == os.path.exists(os.path.join(input_path, "Spot_metadata.csv"))
            == True
        ):
            logging.error(
                "Counts.txt and/or Spotmeta.csv is missing from {}".format(input_path)
            )
            raise ValueError()

        # check if the input path have an tif image, if not, make a pseudo image.
        num_tifs = len([x for x in os.listdir(input_path) if x[-4:] == ".tif"])
        if num_tifs == 1:
            logging.info(
                "Extracting intensity and texture features from matching image."
            )
            img_type = args.img_type
            _ = extract_img_features(input_path, img_type, input_path)
        elif num_tifs == 0:
            logging.info("Use spot cluster probability as pseudo image features")
            cts_fn = os.path.join(input_path, "Counts.txt")
            spots_fn = os.path.join(input_path, "Spot_metadata.csv")
            dp_script_path = os.path.join(sprod_path, "dirichlet_process_clustering.R")
            make_pseudo_img(cts_fn, spots_fn, input_path, "dp", dp_script_path)
            pseudo_img_feature_fn = os.path.join(input_path, 'pseudo_image_features.csv')
        else:
            logging.error(
                "More than one images are present. Please remove the unwanted ones."
            )
            raise ValueError()

        # When the input_type is patches, will run subsampling process.
        if input_type == "patches":
            logging.info("Making subsample patches from counts data.")
            intermediate_path = os.path.join(output_path, "intermediate")
            feature_fn = os.path.join(
                input_path,
                "{}_level_{}_features.csv".format(*image_feature_type.split("_")),
            )
            if not os.path.exists(feature_fn):
                if os.path.exists(pseudo_img_feature_fn):
                    feature_fn = pseudo_img_feature_fn
            if not os.path.exists(intermediate_path):
                os.makedirs(intermediate_path)
            subsample_patches(input_path, intermediate_path, feature_fn, pn, pb)
            input_path = intermediate_path
        elif input_type == "single":
            pass
        else:
            logging.error("Input type must be single or patches")
            raise ValueError()

    # Sprod denoising
    logging.info("Proceed to Sprod denoising.")
    if input_type == "patches":
        logging.info("Sprod-ready data format is patches")
        counts = [x for x in os.listdir(input_path) if "Counts" in x]
        patches = [x.replace("_Counts.txt", "") for x in counts]
        inputs = []
        for j, patch in enumerate(sorted(patches)):
            cts_fn = os.path.join(input_path, patch + "_Counts.txt")
            meta_fn = os.path.join(input_path, patch + "_Spot_metadata.csv")
            feature_fn = os.path.join(input_path, patch + "_F.csv")
            if not (
                os.path.exists(cts_fn)
                == os.path.exists(meta_fn)
                == os.path.exists(feature_fn)
                == True
            ):
                logging.error("At least one patch failed. Please check the output folder.")
                raise ValueError()
            inputs.append([cts_fn, meta_fn, feature_fn])
    else:
        logging.info("Sprod-ready data format is single")
        cts_fn = os.path.join(input_path, "Counts.txt")
        meta_fn = os.path.join(input_path, "Spot_metadata.csv")
        feature_fn = os.path.join(
            input_path,
            "{}_level_{}_features.csv".format(*image_feature_type.split("_")),
        )
        # always tries to use image derived features, then pseudo images.
        if not os.path.exists(feature_fn):
            if os.path.exists(pseudo_img_feature_fn):
                feature_fn = pseudo_img_feature_fn
        if not (
            os.path.exists(cts_fn)
            == os.path.exists(meta_fn)
            == os.path.exists(feature_fn)
            == True
        ):
            logging.error(
                "Counts.txt and/or Spotmeta.csv is missing from {}".format(input_path)
            )
            raise ValueError("Required data is missing!")
        inputs = [[cts_fn, meta_fn, feature_fn]]

    logging.info("Total number of sprod jobs : {}".format(len(inputs)))

    # Starting compling denoise.R jobs.
    list_sprod_cmds = []
    for sprod_job in inputs:
        cts_fn, meta_fn, feature_fn = [os.path.abspath(x) for x in sprod_job]
        if input_type == "patches":
            patch_name = cts_fn.split("/")[-1].replace("_Counts.txt", "")
        else:
            patch_name = "sprod"
        # Pack all parameters for denoise.R job
        sprod_cmd = ["Rscript", sprod_script]
        for sprod_key, param in zip(
            [
                "-e",
                "-c",
                "-f",
                "-n",
                "-r",
                "-u",
                "-k",
                "-l",
                "-t",
                "-m",
                "-x",
                "-d",
                "-s",
                "-o",
                "-p",
            ],
            [
                cts_fn,
                meta_fn,
                feature_fn,
                sprod_npc,
                sprod_R,
                spord_perplexity,
                sprod_latent_dim,
                sprod_graph_reg,
                sprod_weight_reg,
                sprod_margin,
                sprod_umap,
                sprod_diag,
                '/'.join(sprod_path.split('/')[:-1]),
                os.path.abspath(output_path),
                patch_name,
            ],
        ):
            if isinstance(param, bool): # for toggles
                if param:
                    sprod_cmd.append(str(sprod_key)) 
            else: # for kwargs
                sprod_cmd.append(sprod_key)
                sprod_cmd.append(str(param))
        # log file name is packed into cmd
        list_sprod_cmds.append(sprod_cmd + [log_fn])
    if len(list_sprod_cmds) == 1:
        sprod_worker(list_sprod_cmds[0])
    elif len(list_sprod_cmds) > 1:
        with Pool(16) as p:
            _ = p.map(sprod_worker, list_sprod_cmds)

    # last step, stiching all patches back.
    if input_type == "patches":
        stiching_script_path = os.path.join(sprod_path, "slide_seq_stiching.py")
        stiching_subsampled_patches(
            output_path, os.path.join(output_path, "denoised_stiched.hdf")
        )

