// Video Creation Platform - Main JavaScript
// Enhanced interactive functionality with animations and effects

class VideoCreationPlatform {
    constructor() {
        this.currentProject = null;
        this.timelineData = [];
        this.mediaLibrary = [];
        this.isPlaying = false;
        this.currentTime = 0;
        this.duration = 120; // 2 minutes default
        this.zoomLevel = 1;
        this.selectedTrack = null;
        this.collaborators = [];
        this.init();
    }

    init() {
        this.initializeAnimations();
        this.setupEventListeners();
        this.loadSampleData();
        this.initializeTimeline();
        this.setupDragAndDrop();
        this.initializeMediaLibrary();
        this.setupCollaboration();
    }

    initializeAnimations() {
        // Initialize Anime.js animations
        if (typeof anime !== 'undefined') {
            // Hero text animation
            anime({
                targets: '.hero-title .char',
                translateY: [100, 0],
                opacity: [0, 1],
                easing: 'easeOutExpo',
                duration: 1400,
                delay: (el, i) => 30 * i
            });

            // Floating elements animation
            anime({
                targets: '.floating-element',
                translateY: [-20, 20],
                rotate: [-5, 5],
                easing: 'easeInOutSine',
                duration: 4000,
                direction: 'alternate',
                loop: true,
                delay: (el, i) => 1000 * i
            });

            // Timeline tracks animation
            anime({
                targets: '.timeline-track',
                scaleX: [0, 1],
                opacity: [0, 1],
                easing: 'easeOutExpo',
                duration: 800,
                delay: (el, i) => 100 * i
            });
        }

        // Initialize Typed.js for dynamic text
        if (typeof Typed !== 'undefined') {
            new Typed('#typed-text', {
                strings: [
                    'Create stunning videos',
                    'Edit with AI assistance',
                    'Collaborate in real-time',
                    'Export to any platform'
                ],
                typeSpeed: 50,
                backSpeed: 30,
                backDelay: 2000,
                loop: true
            });
        }

        // Initialize particle system with Pixi.js
        this.initializeParticleSystem();
    }

    initializeParticleSystem() {
        if (typeof PIXI !== 'undefined') {
            const canvas = document.getElementById('particle-canvas');
            if (canvas) {
                const app = new PIXI.Application({
                    view: canvas,
                    width: window.innerWidth,
                    height: window.innerHeight,
                    transparent: true,
                    antialias: true
                });

                // Create particle container
                const particleContainer = new PIXI.Container();
                app.stage.addChild(particleContainer);

                // Create particles
                for (let i = 0; i < 50; i++) {
                    const particle = new PIXI.Graphics();
                    particle.beginFill(0x2563EB, 0.3);
                    particle.drawCircle(0, 0, Math.random() * 3 + 1);
                    particle.endFill();
                    
                    particle.x = Math.random() * app.screen.width;
                    particle.y = Math.random() * app.screen.height;
                    particle.vx = (Math.random() - 0.5) * 2;
                    particle.vy = (Math.random() - 0.5) * 2;
                    
                    particleContainer.addChild(particle);
                }

                // Animate particles
                app.ticker.add(() => {
                    particleContainer.children.forEach(particle => {
                        particle.x += particle.vx;
                        particle.y += particle.vy;
                        
                        if (particle.x < 0 || particle.x > app.screen.width) particle.vx *= -1;
                        if (particle.y < 0 || particle.y > app.screen.height) particle.vy *= -1;
                        
                        particle.alpha = 0.3 + Math.sin(Date.now() * 0.001 + particle.x * 0.01) * 0.2;
                    });
                });
            }
        }
    }

    setupEventListeners() {
        // Timeline controls
        document.getElementById('play-btn')?.addEventListener('click', () => this.togglePlayback());
        document.getElementById('pause-btn')?.addEventListener('click', () => this.pausePlayback());
        document.getElementById('stop-btn')?.addEventListener('click', () => this.stopPlayback());
        
        // Timeline scrubbing
        document.getElementById('timeline-scrubber')?.addEventListener('input', (e) => {
            this.currentTime = parseFloat(e.target.value);
            this.updateTimelineDisplay();
        });

        // Zoom controls
        document.getElementById('zoom-in')?.addEventListener('click', () => this.zoomIn());
        document.getElementById('zoom-out')?.addEventListener('click', () => this.zoomOut());
        document.getElementById('zoom-fit')?.addEventListener('click', () => this.zoomFit());

        // Export controls
        document.getElementById('export-btn')?.addEventListener('click', () => this.showExportModal());
        document.getElementById('share-btn')?.addEventListener('click', () => this.showShareModal());

        // Template selection
        document.querySelectorAll('.template-card').forEach(card => {
            card.addEventListener('click', () => this.selectTemplate(card.dataset.templateId));
        });

        // Media upload
        document.getElementById('upload-btn')?.addEventListener('click', () => this.showUploadModal());
        document.getElementById('file-input')?.addEventListener('change', (e) => this.handleFileUpload(e));

        // Collaboration
        document.getElementById('invite-btn')?.addEventListener('click', () => this.showInviteModal());
        document.getElementById('chat-btn')?.addEventListener('click', () => this.toggleChat());

        // Window resize
        window.addEventListener('resize', () => this.handleResize());
    }

    loadSampleData() {
        // Sample timeline data
        this.timelineData = [
            {
                id: 'video-1',
                type: 'video',
                name: 'Intro Clip',
                startTime: 0,
                duration: 15,
                track: 0,
                color: '#EF4444'
            },
            {
                id: 'audio-1',
                type: 'audio',
                name: 'Background Music',
                startTime: 0,
                duration: 120,
                track: 1,
                color: '#10B981'
            },
            {
                id: 'text-1',
                type: 'text',
                name: 'Title Card',
                startTime: 5,
                duration: 10,
                track: 2,
                color: '#3B82F6'
            },
            {
                id: 'image-1',
                type: 'image',
                name: 'Logo Overlay',
                startTime: 0,
                duration: 120,
                track: 3,
                color: '#F59E0B'
            }
        ];

        // Sample media library
        this.mediaLibrary = [
            { id: 1, name: 'intro-video.mp4', type: 'video', duration: 15, thumbnail: 'https://via.placeholder.com/120x68/EF4444/FFFFFF?text=Video' },
            { id: 2, name: 'background-music.mp3', type: 'audio', duration: 180, thumbnail: 'https://via.placeholder.com/120x68/10B981/FFFFFF?text=Audio' },
            { id: 3, name: 'company-logo.png', type: 'image', duration: null, thumbnail: 'https://via.placeholder.com/120x68/3B82F6/FFFFFF?text=Image' },
            { id: 4, name: 'outro-video.mp4', type: 'video', duration: 10, thumbnail: 'https://via.placeholder.com/120x68/8B5CF6/FFFFFF?text=Video' },
            { id: 5, name: 'voiceover.mp3', type: 'audio', duration: 90, thumbnail: 'https://via.placeholder.com/120x68/F59E0B/FFFFFF?text=Audio' },
            { id: 6, name: 'product-shot.jpg', type: 'image', duration: null, thumbnail: 'https://via.placeholder.com/120x68/EC4899/FFFFFF?text=Image' }
        ];

        this.collaborators = [
            { id: 1, name: 'Sarah Chen', avatar: 'https://via.placeholder.com/32x32/EF4444/FFFFFF?text=SC', status: 'online', role: 'Editor' },
            { id: 2, name: 'Mike Johnson', avatar: 'https://via.placeholder.com/32x32/10B981/FFFFFF?text=MJ', status: 'away', role: 'Designer' },
            { id: 3, name: 'Emily Davis', avatar: 'https://via.placeholder.com/32x32/3B82F6/FFFFFF?text=ED', status: 'online', role: 'Producer' }
        ];
    }

    initializeTimeline() {
        const timelineContainer = document.getElementById('timeline-tracks');
        if (!timelineContainer) return;

        timelineContainer.innerHTML = '';

        // Create tracks
        for (let i = 0; i < 4; i++) {
            const track = document.createElement('div');
            track.className = 'timeline-track h-16 bg-slate-800 border-b border-slate-700 relative';
            track.dataset.trackIndex = i;

            const trackLabel = document.createElement('div');
            trackLabel.className = 'absolute left-0 top-0 w-32 h-full bg-slate-900 border-r border-slate-700 flex items-center px-3 text-sm text-slate-300';
            trackLabel.textContent = `Track ${i + 1}`;

            track.appendChild(trackLabel);
            timelineContainer.appendChild(track);
        }

        // Add clips to timeline
        this.timelineData.forEach(clip => {
            this.addClipToTimeline(clip);
        });

        // Update scrubber
        const scrubber = document.getElementById('timeline-scrubber');
        if (scrubber) {
            scrubber.max = this.duration;
            scrubber.value = this.currentTime;
        }

        this.updateTimelineDisplay();
    }

    addClipToTimeline(clip) {
        const track = document.querySelector(`[data-track-index="${clip.track}"]`);
        if (!track) return;

        const clipElement = document.createElement('div');
        clipElement.className = 'timeline-clip absolute h-12 rounded cursor-pointer flex items-center px-2 text-xs text-white font-medium';
        clipElement.style.backgroundColor = clip.color;
        clipElement.style.left = `${(clip.startTime / this.duration) * 100}%`;
        clipElement.style.width = `${(clip.duration / this.duration) * 100}%`;
        clipElement.style.top = '8px';
        clipElement.dataset.clipId = clip.id;

        const clipName = document.createElement('span');
        clipName.className = 'truncate';
        clipName.textContent = clip.name;
        clipElement.appendChild(clipName);

        // Add resize handles
        const leftHandle = document.createElement('div');
        leftHandle.className = 'absolute left-0 top-0 w-1 h-full bg-white bg-opacity-50 cursor-ew-resize';
        clipElement.appendChild(leftHandle);

        const rightHandle = document.createElement('div');
        rightHandle.className = 'absolute right-0 top-0 w-1 h-full bg-white bg-opacity-50 cursor-ew-resize';
        clipElement.appendChild(rightHandle);

        // Event listeners
        clipElement.addEventListener('click', () => this.selectClip(clip.id));
        clipElement.addEventListener('dblclick', () => this.editClip(clip.id));

        track.appendChild(clipElement);
    }

    setupDragAndDrop() {
        const mediaItems = document.querySelectorAll('.media-item');
        const timelineTracks = document.querySelectorAll('.timeline-track');

        mediaItems.forEach(item => {
            item.addEventListener('dragstart', (e) => {
                e.dataTransfer.setData('text/plain', item.dataset.mediaId);
                item.classList.add('opacity-50');
            });

            item.addEventListener('dragend', () => {
                item.classList.remove('opacity-50');
            });
        });

        timelineTracks.forEach(track => {
            track.addEventListener('dragover', (e) => {
                e.preventDefault();
                track.classList.add('bg-blue-900', 'bg-opacity-20');
            });

            track.addEventListener('dragleave', () => {
                track.classList.remove('bg-blue-900', 'bg-opacity-20');
            });

            track.addEventListener('drop', (e) => {
                e.preventDefault();
                track.classList.remove('bg-blue-900', 'bg-opacity-20');
                
                const mediaId = e.dataTransfer.getData('text/plain');
                const rect = track.getBoundingClientRect();
                const x = e.clientX - rect.left - 128; // Account for track label
                const startTime = (x / rect.width) * this.duration;
                
                this.addMediaToTimeline(mediaId, parseInt(track.dataset.trackIndex), startTime);
            });
        });
    }

    initializeMediaLibrary() {
        const mediaGrid = document.getElementById('media-grid');
        if (!mediaGrid) return;

        mediaGrid.innerHTML = '';

        this.mediaLibrary.forEach(media => {
            const mediaItem = document.createElement('div');
            mediaItem.className = 'media-item bg-slate-800 rounded-lg overflow-hidden cursor-pointer hover:bg-slate-700 transition-colors';
            mediaItem.draggable = true;
            mediaItem.dataset.mediaId = media.id;

            mediaItem.innerHTML = `
                <img src="${media.thumbnail}" alt="${media.name}" class="w-full h-20 object-cover">
                <div class="p-2">
                    <div class="text-xs text-slate-300 truncate">${media.name}</div>
                    <div class="text-xs text-slate-400">${media.type.toUpperCase()}</div>
                    ${media.duration ? `<div class="text-xs text-slate-400">${this.formatTime(media.duration)}</div>` : ''}
                </div>
            `;

            mediaItem.addEventListener('click', () => this.previewMedia(media.id));
            mediaGrid.appendChild(mediaItem);
        });
    }

    setupCollaboration() {
        const collaboratorsList = document.getElementById('collaborators-list');
        if (!collaboratorsList) return;

        collaboratorsList.innerHTML = '';

        this.collaborators.forEach(collaborator => {
            const collaboratorItem = document.createElement('div');
            collaboratorItem.className = 'flex items-center space-x-2 p-2 hover:bg-slate-800 rounded-lg cursor-pointer';

            const statusColor = {
                online: 'bg-green-500',
                away: 'bg-yellow-500',
                offline: 'bg-gray-500'
            }[collaborator.status];

            collaboratorItem.innerHTML = `
                <div class="relative">
                    <img src="${collaborator.avatar}" alt="${collaborator.name}" class="w-8 h-8 rounded-full">
                    <div class="absolute -bottom-1 -right-1 w-3 h-3 ${statusColor} rounded-full border-2 border-slate-900"></div>
                </div>
                <div class="flex-1 min-w-0">
                    <div class="text-sm text-slate-300 truncate">${collaborator.name}</div>
                    <div class="text-xs text-slate-400">${collaborator.role}</div>
                </div>
            `;

            collaboratorItem.addEventListener('click', () => this.showCollaboratorInfo(collaborator.id));
            collaboratorsList.appendChild(collaboratorItem);
        });
    }

    // Playback Controls
    togglePlayback() {
        this.isPlaying = !this.isPlaying;
        if (this.isPlaying) {
            this.startPlayback();
        } else {
            this.pausePlayback();
        }
    }

    startPlayback() {
        this.isPlaying = true;
        const playBtn = document.getElementById('play-btn');
        if (playBtn) {
            playBtn.innerHTML = '<i class="fas fa-pause"></i>';
        }

        this.playbackInterval = setInterval(() => {
            this.currentTime += 0.1;
            if (this.currentTime >= this.duration) {
                this.stopPlayback();
                return;
            }
            this.updateTimelineDisplay();
        }, 100);
    }

    pausePlayback() {
        this.isPlaying = false;
        const playBtn = document.getElementById('play-btn');
        if (playBtn) {
            playBtn.innerHTML = '<i class="fas fa-play"></i>';
        }
        
        if (this.playbackInterval) {
            clearInterval(this.playbackInterval);
        }
    }

    stopPlayback() {
        this.pausePlayback();
        this.currentTime = 0;
        this.updateTimelineDisplay();
    }

    // Zoom Controls
    zoomIn() {
        this.zoomLevel = Math.min(this.zoomLevel * 1.5, 10);
        this.updateTimelineDisplay();
    }

    zoomOut() {
        this.zoomLevel = Math.max(this.zoomLevel / 1.5, 0.1);
        this.updateTimelineDisplay();
    }

    zoomFit() {
        this.zoomLevel = 1;
        this.updateTimelineDisplay();
    }

    // Timeline Updates
    updateTimelineDisplay() {
        // Update scrubber
        const scrubber = document.getElementById('timeline-scrubber');
        if (scrubber) {
            scrubber.value = this.currentTime;
        }

        // Update time display
        const timeDisplay = document.getElementById('time-display');
        if (timeDisplay) {
            timeDisplay.textContent = `${this.formatTime(this.currentTime)} / ${this.formatTime(this.duration)}`;
        }

        // Update playhead position
        const playhead = document.getElementById('playhead');
        if (playhead) {
            playhead.style.left = `${(this.currentTime / this.duration) * 100}%`;
        }
    }

    // Media Management
    addMediaToTimeline(mediaId, trackIndex, startTime) {
        const media = this.mediaLibrary.find(m => m.id == mediaId);
        if (!media) return;

        const newClip = {
            id: `clip-${Date.now()}`,
            type: media.type,
            name: media.name,
            startTime: Math.max(0, startTime),
            duration: media.duration || 10,
            track: trackIndex,
            color: this.getColorForType(media.type)
        };

        this.timelineData.push(newClip);
        this.addClipToTimeline(newClip);
    }

    getColorForType(type) {
        const colors = {
            video: '#EF4444',
            audio: '#10B981',
            image: '#3B82F6',
            text: '#F59E0B'
        };
        return colors[type] || '#6B7280';
    }

    previewMedia(mediaId) {
        const media = this.mediaLibrary.find(m => m.id == mediaId);
        if (!media) return;

        // Show preview modal or update preview panel
        this.showNotification(`Previewing: ${media.name}`);
    }

    // Collaboration
    showCollaboratorInfo(collaboratorId) {
        const collaborator = this.collaborators.find(c => c.id == collaboratorId);
        if (!collaborator) return;

        this.showNotification(`${collaborator.name} - ${collaborator.role} (${collaborator.status})`);
    }

    // Utility Functions
    formatTime(seconds) {
        const mins = Math.floor(seconds / 60);
        const secs = Math.floor(seconds % 60);
        return `${mins}:${secs.toString().padStart(2, '0')}`;
    }

    selectClip(clipId) {
        // Remove previous selection
        document.querySelectorAll('.timeline-clip').forEach(clip => {
            clip.classList.remove('ring-2', 'ring-blue-500');
        });

        // Add selection to clicked clip
        const clipElement = document.querySelector(`[data-clip-id="${clipId}"]`);
        if (clipElement) {
            clipElement.classList.add('ring-2', 'ring-blue-500');
        }

        this.selectedTrack = clipId;
        this.showPropertiesPanel(clipId);
    }

    editClip(clipId) {
        const clip = this.timelineData.find(c => c.id === clipId);
        if (!clip) return;

        this.showNotification(`Editing: ${clip.name}`);
        // Open clip editor modal
    }

    showPropertiesPanel(clipId) {
        const clip = this.timelineData.find(c => c.id === clipId);
        if (!clip) return;

        const propertiesPanel = document.getElementById('properties-panel');
        if (propertiesPanel) {
            propertiesPanel.innerHTML = `
                <div class="p-4">
                    <h3 class="text-lg font-semibold text-white mb-4">Properties</h3>
                    <div class="space-y-4">
                        <div>
                            <label class="block text-sm text-slate-400 mb-1">Name</label>
                            <input type="text" value="${clip.name}" class="w-full bg-slate-700 text-white px-3 py-2 rounded">
                        </div>
                        <div>
                            <label class="block text-sm text-slate-400 mb-1">Start Time</label>
                            <input type="number" value="${clip.startTime}" step="0.1" class="w-full bg-slate-700 text-white px-3 py-2 rounded">
                        </div>
                        <div>
                            <label class="block text-sm text-slate-400 mb-1">Duration</label>
                            <input type="number" value="${clip.duration}" step="0.1" class="w-full bg-slate-700 text-white px-3 py-2 rounded">
                        </div>
                        <div>
                            <label class="block text-sm text-slate-400 mb-1">Track</label>
                            <select class="w-full bg-slate-700 text-white px-3 py-2 rounded">
                                <option value="0" ${clip.track === 0 ? 'selected' : ''}>Track 1</option>
                                <option value="1" ${clip.track === 1 ? 'selected' : ''}>Track 2</option>
                                <option value="2" ${clip.track === 2 ? 'selected' : ''}>Track 3</option>
                                <option value="3" ${clip.track === 3 ? 'selected' : ''}>Track 4</option>
                            </select>
                        </div>
                    </div>
                </div>
            `;
        }
    }

    // Modal Functions
    showExportModal() {
        const modal = document.getElementById('export-modal');
        if (modal) {
            modal.classList.remove('hidden');
            modal.classList.add('flex');
        }
    }

    showShareModal() {
        const modal = document.getElementById('share-modal');
        if (modal) {
            modal.classList.remove('hidden');
            modal.classList.add('flex');
        }
    }

    showUploadModal() {
        const modal = document.getElementById('upload-modal');
        if (modal) {
            modal.classList.remove('hidden');
            modal.classList.add('flex');
        }
    }

    showInviteModal() {
        const modal = document.getElementById('invite-modal');
        if (modal) {
            modal.classList.remove('hidden');
            modal.classList.add('flex');
        }
    }

    toggleChat() {
        const chatPanel = document.getElementById('chat-panel');
        if (chatPanel) {
            chatPanel.classList.toggle('hidden');
        }
    }

    // Notification System
    showNotification(message, type = 'info') {
        const notification = document.createElement('div');
        notification.className = `fixed top-4 right-4 px-6 py-3 rounded-lg text-white z-50 ${
            type === 'success' ? 'bg-green-600' : 
            type === 'error' ? 'bg-red-600' : 
            type === 'warning' ? 'bg-yellow-600' : 'bg-blue-600'
        }`;
        notification.textContent = message;

        document.body.appendChild(notification);

        // Animate in
        anime({
            targets: notification,
            translateX: [300, 0],
            opacity: [0, 1],
            easing: 'easeOutExpo',
            duration: 300
        });

        // Remove after 3 seconds
        setTimeout(() => {
            anime({
                targets: notification,
                translateX: [0, 300],
                opacity: [1, 0],
                easing: 'easeInExpo',
                duration: 300,
                complete: () => {
                    document.body.removeChild(notification);
                }
            });
        }, 3000);
    }

    // Resize Handler
    handleResize() {
        // Update particle canvas size
        const canvas = document.getElementById('particle-canvas');
        if (canvas) {
            canvas.width = window.innerWidth;
            canvas.height = window.innerHeight;
        }

        // Update timeline display
        this.updateTimelineDisplay();
    }

    // Template Selection
    selectTemplate(templateId) {
        this.showNotification(`Selected template: ${templateId}`);
        // Apply template to current project
    }

    // File Upload
    handleFileUpload(event) {
        const files = Array.from(event.target.files);
        files.forEach(file => {
            this.showNotification(`Uploading: ${file.name}`);
            // Process file upload
        });
    }
}

// Initialize the application when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    window.videoPlatform = new VideoCreationPlatform();
});

// Global utility functions
function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.add('hidden');
        modal.classList.remove('flex');
    }
}

function showComingSoon() {
    if (window.videoPlatform) {
        window.videoPlatform.showNotification('Coming soon!', 'info');
    }
}