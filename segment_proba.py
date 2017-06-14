import argparse
import itertools
import json
import os

import chainer
import numpy as np
import nibabel as nib
import pandas as pd

from load import load_nifti
from model import VoxResNet


parser = argparse.ArgumentParser(description="calculate class probabilities with VoxResNet")
parser.add_argument(
    "--input_file", "-i", type=str,
    help="input json file of test dataset")
parser.add_argument(
    "--output_suffix", "-o", type=str, default="_segTRI_proba_{}.nii.gz",
    help="result of the segmentation, default=_segTRI_proba_{}.nii.gz")
parser.add_argument(
    "--model", "-m", type=str,
    help="a file containing parameters of trained VoxResNet")
parser.add_argument(
    "--shape", type=int, nargs="*", action="store",
    default=[80, 80, 80],
    help="input patch shape of VoxResNet, default=[80, 80, 80]")
parser.add_argument(
    "--gpu", "-g", default=-1, type=int,
    help="negative value indicates no gpu, default=-1")
parser.add_argument(
    "--n_tiles", type=int, nargs="*", action="store",
    default=[4, 4, 4],
    help="number of tiles along each axis")
args = parser.parse_args()
print(args)

with open(args.input_file) as f:
    dataset = json.load(f)
test_df = pd.DataFrame(dataset["data"])

vrn = VoxResNet(dataset["in_channels"], dataset["n_classes"])
chainer.serializers.load_npz(args.model, vrn)

if args.gpu >= 0:
    chainer.cuda.get_device(args.gpu).use()
    vrn.to_gpu()
    xp = chainer.cuda.cupy
else:
    xp = np

for image_path, subject in zip(test_df["image"], test_df["subject"]):
    image, affine = load_nifti(image_path, with_affine=True)
    image = image.transpose(3, 0, 1, 2)
    slices = [[], [], []]
    for img_len, patch_len, slices_, n_tile in zip(image.shape[1:], args.shape, slices, args.n_tiles):
        assert img_len > patch_len, (img_len, patch_len)
        assert img_len < patch_len * n_tile, "{} must be smaller than {} x {}".format(img_len, patch_len, n_tile)
        stride = int((img_len - patch_len) / (n_tile - 1))
        for i in range(n_tile - 1):
            slices_.append(slice(i * stride, i * stride + patch_len))
        slices_.append(slice(img_len - patch_len, img_len))
    output = np.zeros((dataset["n_classes"],) + image.shape[1:], dtype=np.float32)
    for xslice, yslice, zslice in itertools.product(*slices):
        patch = image[slice(None), xslice, yslice, zslice]
        patch = np.expand_dims(patch, 0)
        x = xp.asarray(patch)
        output[slice(None), xslice, yslice, zslice] += chainer.cuda.to_cpu(
            vrn(x).data[0])

    output /= np.sum(output, axis=0, keepdims=True)

    for i, y in enumerate(output):
        nib.save(
            nib.Nifti1Image(y, affine),
            os.path.join(
                os.path.dirname(image_path),
                subject + args.output_suffix.format(i)))
