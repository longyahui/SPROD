# Rversion>=4, need distances, Rcpp

#######  read arguments  ################
suppressPackageStartupMessages(require(optparse))
option_list = list(
  make_option(c("-e", "--Exp"), action="store", default=NA, 
              type='character',help="Expression matrix"),
  make_option(c("-c", "--Cspot"), action="store", 
              default=NA, type='character',
              help="Spot metadata, contains X, Y coordinates."),
  make_option(c("-f", "--ImageFeature"), action="store", 
              default=NA,type = 'character',
              help="Extracted image features"),
  make_option(c("-n", "--numberPC"), action="store",
              default = -1,type = 'double',
              help="# Number of PCs to use. positive integers. by default set to -1 to use the number of PCs the same as the numebr of features"),
  make_option(c("-x","--umap"),action="store_true",dest = "umap",
              default = FALSE,type = "logical",
              help ="# Use UMAP of Image features or NOT. By default set to FALSE, which the PCA is used to transform IF."),
  make_option(c("-g","--diagnose"),action="store_true",dest = "diagnose",
              default = FALSE,type = "logical",
              help ="# Generate diagnostic figures or NOT. By default set to FALSE."),
  make_option(c("-r", "--Rratio"), action="store", 
              default=0.08,type = 'double',
              help="Spot neighborhood radius ratio, 0-1, radius=R*min(xmax-xmin,ymax-ymin)"), 
  make_option(c("-u", "--U"), action="store", 
              default = 250,type = 'double',
              help="# perplexity, Tunable"),
  make_option(c("-k", "--K"), action="store", 
              default=10,type = 'double',
              help="latent space dimension, Tunable"), 
  make_option(c("-l", "--lambda"), action="store", 
              default = 0.4,type = 'double',
              help="# regularizer, tunable"),
  make_option(c("-t", "--L_E"), action="store", 
              default=0.625,type = 'double',
              help="regularizer for denoising"), 
  make_option(c("-m", "--margin"), action="store", 
              default = 0.001,type = 'double',
              help="Margin for bisection search, smaller = slower => accuracy u"),
  make_option(c("-d","--diagNeighbor"),action="store_true",
              default = FALSE, type = "logical",
              help = "To prevent over smooth."),
  make_option(c("-s", "--scriptPath"), action="store",
              default=NA, type ='character',
              help="path to the software folder"),
  make_option(c("-o", "--outputPath"), action="store", 
              default=NA, type ='character',
              help="Output path"),
  make_option(c("-p", "--projectID"), action="store", 
              default=NA, type = 'character',
              help="# project name, First part of names in the output")
  )
opt = parse_args(OptionParser(option_list=option_list))

###########  define input  ##############
cat("Inputting...\n")

counts_fn <- opt$Exp
spot_meta_fn <- opt$Cspot
image_features_fn <- opt$ImageFeature
N_PC=opt$numberPC
diagnose = opt$diagnose
um =opt$umap
R_ratio=opt$Rratio # Spot neighborhood radius ratio, 0-1, radius=R*min(xmax-xmin,ymax-ymin)
U=opt$U # perplexity, Tunable
K=opt$K # latent space dimension, Tunable
LAMBDA=opt$lambda # regularizer, tunable
L_E=opt$L_E # regularizer for denoising
margin=opt$margin # Margin for bisection search, smaller = slower => accuracy up 
d = opt$diagNeighbor
script_path=opt$scriptPath # path to the software folder
output_path=opt$outputPath # output path
diagnose=opt$diagnose
project_name=opt$projectID


cat(paste("N_PC:",N_PC,"umap",um,"R_ratio:",R_ratio,"U:",U,"K",K,"LAMBDA:",LAMBDA,"L_E",L_E,"margin:",margin,"W_diag",d,"project ID:",project_name))
cat("\n\n")

######  load environment  #############

library(distances)
library(Rcpp)
library(dplyr)

if (Sys.getenv("RSTUDIO") == "1")
{
  source(paste(script_path,"/sprod/bisection/bisection.R",sep=""))
}else
{
  sourceCpp(paste(script_path,"/sprod/bisection/bisection_par.cpp",sep=""))
}

source(paste(script_path,"/sprod/denoise_functions.R",sep=""))

# (1) in practice, we specify an even stronger sufficient condition
# regarding the relationship between d(y) and 1-(p_n_n + t(p_n_n))/2
# this part is tricky. need to think about how to justify 
# for this theorectically, in the best way
# (2) test this in simulation carefully but we want to be vague 
# about this in the paper
Power_tsne_factor=7

##########read input######
E=as.matrix(read.table(counts_fn,row.names = 1,header = T))
C=read.csv(spot_meta_fn,row.names = 1,header = T,stringsAsFactors=F)
R=min(max(C$X)-min(C$X),max(C$Y)-min(C$Y))*R_ratio
IF=as.matrix(read.csv(image_features_fn,row.names=1,header=T))
if (any(rownames(E)!=rownames(C)) || any(rownames(E)!=rownames(IF)))
{stop("Spot IDs mismatch!")}

#######  initialization  ###############
cat("initializing...\n")
# proximity matrix
P=as.matrix(dist(C[,c("X","Y")],diag = FALSE))<=R
table(P)
diag(P)=FALSE # set self proximity to 0
P[lower.tri(P)]=F # for ensuring alpha_n1_n2=alpha_n2_n1
# Initialize graph weight matrix, symmetrical.
# enforce a_n1_n2 == a_n2_n1
ALPHA=diag(dim(IF)[1])
#S =1
ALPHA[]=1/2*P

# Preprocessing F matrix
IF=scale(IF,center=TRUE,scale=TRUE)
IF0=IF #save the raw image features for plots#
if (um){
  IF=umap::umap(IF)$layout
  cat("IF: UMAP done!\n")
}else{
  if (N_PC>0) {
    IF=prcomp(IF)$x[,1:min(N_PC,dim(IF)[2])]
  }else{
    IF=prcomp(IF)$x[,1:dim(IF)[2]]
    cat("IF: All PCs are selected!\n")
  }
  cat("IF: PCA done!\n")
}
cat("IF is:\n")
head(IF)
# Preprocessing the features with PCA or tSNE, optional
#cat(paste0("Image feature:",head(IF),"\n"))
#######  spatial denoise  ################
cat("denoising...\n")
ptm <- proc.time()
# similarity between spots in the original image feature space.
sigma_n=find_sigma_n_all(t(IF),U,margin)
euc_dist2=as.matrix(dist(IF,diag = FALSE))^2
# probably will need some work to improve the computational efficiency
# of p_n_n. future work
p_n_n=sapply(1:dim(IF)[1], 
             function(n) calculate_spot_dist(n,sigma_n,euc_dist2))
p_nn_tsne=1-(p_n_n + t(p_n_n))/2
p_nn_tsne=p_nn_tsne^(dim(IF)[1]/Power_tsne_factor)

# Build a graph based on image features and spot closeness
while (1==1)
{
  ALPHA[]=optim(as.vector(ALPHA),fn=fr,gr=gr,method='L-BFGS-B',
                lower=0,upper=P*1,data=list(LAMBDA, p_nn_tsne, P , K),
                control=list(trace=T))$par 
  
  if (sum(ALPHA>0)>0) {break}
  cat("Lambda is set too large (trivial solution)!\n")
  LAMBDA=LAMBDA*0.8
  cat(paste("Resetting to",LAMBDA,"\n"))
}

table(ALPHA>0)
table(P==T)
if (sum(ALPHA>0)/sum(P==T)>0.9) {warning("Lambda may be set too small!")}
if (sum(ALPHA>0)/sum(P==T)<0.1) {warning("Lambda may be set too large!")}
ALPHA=ALPHA+t(ALPHA)
proc.time() - ptm
# Denoise expression matrix based on the graph
G = ALPHA/1
rownames(G)=colnames(G)=rownames(E)
G[1:4,1:3]
############diagnosing#########
if(diagnose){
  cat("diagnose...\n")
  Stack <- data.frame(S4Vectors::stack(G))
  head(Stack)
  Stack <- Stack[which(Stack$value>0),]
  Stack$x1 <- C[Stack$row,"X"]
  Stack$y1 <- C[Stack$row,"Y"]
  Stack$x2 <- C[Stack$col,"X"]
  Stack$y2 <- C[Stack$col,"Y"]
  
  
  cellNames= data.frame(t(Stack[,1:2]))
  Stack$pair = sapply(cellNames,function(x){paste0(sort(x)[1],sort(x)[2])})
  ## Generate the t_SNE plot
  library(Rtsne)

  tsne <- Rtsne(IF0,check_duplicates = FALSE)
  rownames(tsne$Y)= rownames(IF0)
  colnames(tsne$Y) = c("tsne1","tsne2")
  # You can change the value of perplexity and see how the plot changes
  Stack$tsne11 <- tsne$Y[Stack$row,"tsne1"]
  Stack$tsne12 <- tsne$Y[Stack$row,"tsne2"]
  Stack$tsne21 <- tsne$Y[Stack$col,"tsne1"]
  Stack$tsne22 <- tsne$Y[Stack$col,"tsne2"]
  
  if(um){
    colnames(IF) = c("umap1","umap2")
    Stack$umap11 <- IF[Stack$row,"umap1"]
    Stack$umap12 <- IF[Stack$row,"umap2"]
    Stack$umap21 <- IF[Stack$col,"umap1"]
    Stack$umap22 <- IF[Stack$col,"umap2"]
    
#    IFpc=prcomp(IF0)$x[,1:2]
#    Stack$pc11 <- IFpc[Stack$row,"PC1"]
#    Stack$pc12 <- IFpc[Stack$row,"PC2"]
#    Stack$pc21 <- IFpc[Stack$col,"PC1"]
#    Stack$pc22 <- IFpc[Stack$col,"PC2"]
    
  }else{
#    colnames(IF) = paste0(rep("PC",ncol(IF)),c(1:ncol(IF)))
#    Stack$pc11 <- IF[Stack$row,"PC1"]
#    Stack$pc12 <- IF[Stack$row,"PC2"]
#    Stack$pc21 <- IF[Stack$col,"PC1"]
 #   Stack$pc22 <- IF[Stack$col,"PC2"]
    
    IFump=umap::umap(IF0)$layout
    colnames(IFump) = c("umap1","umap2")
    Stack$umap11 <- IFump[Stack$row,"umap1"]
    Stack$umap12 <- IFump[Stack$row,"umap2"]
    Stack$umap21 <- IFump[Stack$col,"umap1"]
    Stack$umap22 <- IFump[Stack$col,"umap2"]
  }
  
  head(Stack)

  #######Figure out diagnose########
  
  library(ggplot2)
  if (length(table(Stack$pair)) >5000){
    Stack_plot =filter(Stack,pair %in% sample(names(table(Stack$pair)),5000))
  }else{
    Stack_plot =Stack
  }
  
  cat(paste0("The number of edges to plot is:",length(table(Stack_plot$pair)),"\n"))
  cat("Figuring Out...\n")
  p1 =ggplot(Stack_plot,aes(x=x1,y=y1))+
    geom_line(aes(group=pair,color=value,alpha=value))+
    xlab("X")+
    ylab("Y")+
    ggtitle("Spatial")

    p2 =ggplot(Stack_plot,aes(x=tsne11,y=tsne12)) + 
    geom_line(aes(group=pair
                  ,color=value
                  ,alpha=value))+
    xlab("TSNE1")+
    ylab("TSNE2")+
    ggtitle("TSNE")
  
  p3 =ggplot(Stack_plot,aes(x=umap11,y=umap12)) + 
    geom_line(aes(group=pair
                  ,color=value
                  ,alpha=value))+
    xlab("UMAP1")+
    ylab("UMAP2")+
    ggtitle("UMAP")
  
#  p4 = ggplot(Stack_plot,aes(x=pc11,y=pc12)) + 
#    geom_line(aes(group=pair
#                  ,color=value
#                  ,alpha=value))+
#    xlab("PC1")+
#    ylab("PC2")+
#    ggtitle("PCA")
  
  library(gridExtra)
  library(grid)
  pdf(paste0(output_path,"/",project_name,"_Spot_Similarity.pdf"),
      width = 12,height = 4)
#  grid.arrange(p1,p2,p3,p4,ncol=2,nrow=2,
#               widths=c(1.5,1.5),
#               heights=c(1.5,1.5),
#               top=paste0(project_name,"_Spot Similarity in Detected Graph"))
    grid.arrange(p1,p2,p3,ncol=3,nrow=1,
                 widths=c(1,1,1),
                 heights=1,
                 top=paste0(project_name,"_Spot Similarity in Detected Graph"))
  dev.off()
}

W = solve(diag(1, dim(G)[1]) + L_E * (diag(rowSums(G)) - G))
if (d){
  diag_W=diag(W)
  W[G==0]=0
  diag(W)=diag_W
  W=W/rowSums(W)
  cat("d is TRUE!\n")
}

E_denoised =  W %*% E

# retrieve the embedding space
cat("retrieving...\n")
Q = diag(1, dim(ALPHA)[1])+4*diag(rowSums(ALPHA))-4*ALPHA
Q_inv=solve(Q)
Q_inv=(Q_inv+t(Q_inv))/2

tmp=Q
tmp[]=1/dim(Q_inv)[1]
tmp=diag(dim(Q_inv)[1])-tmp

cat("eigen...\n")
ptm <- proc.time()
decomposition=eigen(tmp %*% Q_inv %*% tmp)
proc.time() - ptm
Y=decomposition$vectors %*% diag(decomposition$values)^0.5
Y=Y[,1:K]

#########  output  ################
cat("outputing...\n")
rownames(E_denoised)=rownames(E)
write.table(round(E_denoised,d=5),
            paste0(output_path,'/',project_name,'_Denoised_matrix.txt'),
            sep='\t',row.names = T,col.names = T,quote=F)

write.table(round(G,d=5),
            paste0(output_path,'/',project_name,'_Detected_graph.txt'),
            sep='\t',row.names = T,col.names = T,quote=F)

rownames(Y)=rownames(E)
colnames(Y)=paste0("Component",1:dim(Y)[2])
write.table(round(Y,d=5),
            paste0(output_path,'/',project_name,'_Latent_space.txt'),
            sep='\t',row.names = T,col.names = T,quote=F)