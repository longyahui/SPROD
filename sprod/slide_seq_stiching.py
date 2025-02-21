from numpy.core.defchararray import index
import pandas as pd
import os
import sys
import numpy as np

def stiching_denoised_patches(input_path, output_fn = None):
    cts_files = sorted([x for x in os.listdir(input_path) if 'Counts.txt' in x])
    denoised_fns = sorted([x for x in os.listdir(input_path) if 'denoised' in x])
    assert(len(cts_files) == len(denoised_fns)), 'Slideseq patch data not properly denoised'

    denoised_mtx = pd.DataFrame()
    for cts_fn in cts_files:
        abs_cts_fn = os.path.join(input_path,cts_fn)
        core_name = cts_fn.replace('_Counts.txt','')
        metadata_fn = abs_cts_fn.replace('Counts.txt','Spot_metadata.csv')
        denoised_fn = abs_cts_fn.replace('Counts.txt', 'denoised/Denoised_matrix.txt')
        metadata = pd.read_csv(metadata_fn, index_col=0)
        denoised_cts = pd.read_csv(denoised_fn, index_col=0, sep='\t')
        core_idx = metadata[metadata.patch_core == core_name].index
        denoised_mtx = denoised_mtx.append(denoised_cts.loc[core_idx])
    
    if output_fn is None:
        output_fn = input_path.replace('/patches','/denoised_cts.h5df')

    denoised_mtx.to_hdf(output_fn, key='denoised')

def stiching_subsampled_patches(input_path, output_fn):
    cts_files = sorted([x for x in os.listdir(input_path) if 'Denoised' in x])
    batches = list(set(['_'.join(x.split('_')[:2]) for x in cts_files]))
    tmp = pd.read_csv(
        os.path.join(input_path, cts_files[0]),
        index_col=0, sep='\t',nrows=5)
    n_genes = tmp.shape[1]
    gene_names = tmp.columns
    for i, batch in enumerate(batches):
        patch_cts = [x for x in cts_files if batch in x]
        patch_cts = [os.path.join(input_path, x) for x in patch_cts]
        # get number of total barcodes
        if i == 0:
            patch_metas = [
                x.replace('Denoised_matrix.txt','Latent_space.txt') for x in patch_cts]
            n_barcodes = 0
            for meta in patch_metas:
                n_barcodes += pd.read_csv(meta, sep='\t').shape[0]
        barcode_list = []
        cts_array = np.zeros((n_barcodes, n_genes))
        top = 0
        for j, cts_fn in enumerate(patch_cts):
            print('Processing {}'.format(cts_fn))
            cts = pd.read_csv(cts_fn, index_col=0, sep='\t')
            barcode_list += cts.index.tolist()
            delta = cts.shape[0]
            cts_array[top:top+delta] = cts.values
            top = top + delta

        barcode_list = np.array(barcode_list)
        barcode_order = np.argsort(barcode_list)
        cts_array = cts_array[barcode_order,:]
        barcode_list = barcode_list[barcode_order]

        if i == 0:
            pooled_barcodes = barcode_list
            pooled_cts = cts_array
        else:
            assert((barcode_list == pooled_barcodes).all()), 'Barcodes in batches does not match!'
            pooled_cts += cts_array

    pooled_cts = pooled_cts / len(batches)
    pooled_cts = pd.DataFrame(pooled_cts, index = pooled_barcodes, columns=gene_names)
    pooled_cts.to_hdf(output_fn, key = 'denoised')

if __name__ == '__main__':
    input_path = sys.argv[1]
    # input_path = '/project/shared/xiao_wang/projects/MOCCA/data/Sprod_ready_data/slideseq/Puck_200115_08/subsample_patches/denoised'
    try:
        output_fn = sys.argv[2]
        # output_fn = '/project/shared/xiao_wang/projects/MOCCA/data/Sprod_ready_data/slideseq/Puck_200115_08/subsample_patches/denoised_counts.hdf'
    except IndexError:
        output_fn = None
    # stiching_denoised_patches(input_path, output_fn)
    stiching_subsampled_patches(input_path, output_fn)




